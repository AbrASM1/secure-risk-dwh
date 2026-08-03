import json
import secrets
from dataclasses import replace
from pathlib import Path

import oracledb
import polars as pl
import pytest

from srdwh.cli import main
from srdwh.config import load_settings
from srdwh.contracts.landing import MANIFEST
from srdwh.generate.landing import write_landing
from srdwh.ingest.registry import function
from tests.integration.db import Connect, rows

pytestmark = pytest.mark.db
SETTINGS = Path(__file__).resolve().parents[2] / "srdwh.toml"
REF = SETTINGS.parent / "db" / "ref"
SECOND = "exposure/as_of_date=2025-10-31"
Events = list[dict[str, object]]


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    profile = replace(load_settings(SETTINGS).profile("ci"), seed=secrets.randbelow(10**9))
    write_landing(profile, REF, tmp_path)
    return tmp_path


def run(data_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> tuple[int, Events]:
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["srdwh", "run", "--profile", "ci", "--data-dir", str(data_dir)])
    with pytest.raises(SystemExit) as stop:
        main()
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    return int(str(stop.value.code)), events


def manifests(data_dir: Path) -> dict[str, dict[str, object]]:
    return {
        str(path.parent.relative_to(data_dir / "landing")): json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(data_dir.glob("landing/*/*/manifest.json"))
    }


def registry(connection: oracledb.Connection, sha256: object) -> list[tuple[object, ...]]:
    return rows(
        connection,
        "SELECT status, rows_expected, rows_loaded FROM srdwh_owner.ops_load_registry "
        "WHERE sha256 = :sha ORDER BY load_id",
        sha=sha256,
    )


def named(events: Events, event: str) -> Events:
    return [e for e in events if e["event"] == event]


def test_loaded_file_skipped(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    system_connection: oracledb.Connection,
) -> None:
    code, events = run(data_dir, capsys, monkeypatch)
    assert code == 0
    assert len(named(events, "load_end")) == 6
    assert events[-1]["event"] == "run_end"
    assert events[-1]["exit_code"] == 0
    for manifest in manifests(data_dir).values():
        assert registry(system_connection, manifest["sha256"]) == [("LOADED", manifest["rows"], manifest["rows"])]
    code, events = run(data_dir, capsys, monkeypatch)
    assert code == 0
    assert (len(named(events, "load_skipped")), named(events, "load_end")) == (6, [])
    assert all(len(registry(system_connection, m["sha256"])) == 1 for m in manifests(data_dir).values())


def test_partition_without_manifest_skipped(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    system_connection: oracledb.Connection,
) -> None:
    held = manifests(data_dir)[SECOND]
    (data_dir / "landing" / SECOND / MANIFEST).unlink()
    code, events = run(data_dir, capsys, monkeypatch)
    assert code == 0
    assert [(e["feed"], e["as_of"]) for e in named(events, "partition_not_ready")] == [("exposure", "2025-10-31")]
    assert len(named(events, "load_end")) == 5
    assert registry(system_connection, held["sha256"]) == []


def test_structural_check_exit_1(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    system_connection: oracledb.Connection,
) -> None:
    path = data_dir / "landing" / SECOND / MANIFEST
    tampered = json.loads(path.read_text(encoding="utf-8")) | {"sha256": "f" * 64}
    path.write_text(json.dumps(tampered), encoding="utf-8")
    code, events = run(data_dir, capsys, monkeypatch)
    assert code == 1
    (failure,) = named(events, "structural_check_failed")
    assert failure["message"] == f"{SECOND}/part-0.parquet: sha256 differs from the manifest"
    assert len(named(events, "load_end")) == 1
    assert registry(system_connection, "f" * 64) == []
    assert (events[-1]["event"], events[-1]["exit_code"]) == ("run_end", 1)


def test_failed_load_retried(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    connect: Connect,
    system_connection: oracledb.Connection,
) -> None:
    first = manifests(data_dir)["counterparty/as_of_date=2025-10-31"]
    with connect("SRDWH_ETL") as connection:
        arguments = [
            "counterparty",
            pl.Series([first["as_of_date"]]).str.to_date()[0],
            "probe",
            first["sha256"],
            first["rows"],
        ]
        function(connection, "register_load", None, *arguments)
        connection.commit()
    code, _ = run(data_dir, capsys, monkeypatch)
    assert code == 0
    assert [status for status, *_ in registry(system_connection, first["sha256"])] == ["FAILED", "LOADED"]


def test_bronze_rows_as_delivered(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    system_connection: oracledb.Connection,
) -> None:
    code, events = run(data_dir, capsys, monkeypatch)
    assert code == 0
    load_id = named(events, "load_end")[0]["load_id"]
    delivered = pl.read_parquet(data_dir / "landing" / "counterparty/as_of_date=2025-10-31/part-0.parquet")
    stored = rows(
        system_connection,
        "SELECT src_row, cpty_id, lei, src_file, TO_CHAR(ingested_at, 'TZH:TZM') "
        "FROM srdwh_owner.brz_counterparty WHERE load_id = :load_id ORDER BY src_row",
        load_id=load_id,
    )
    assert [row[0] for row in stored] == list(range(1, delivered.height + 1))
    assert [row[1] or "" for row in stored] == delivered["cpty_id"].to_list()
    assert [row[2] or "" for row in stored] == delivered["lei"].to_list()
    assert {row[3] for row in stored} == {"counterparty/as_of_date=2025-10-31/part-0.parquet"}
    assert {row[4] for row in stored} == {"+00:00"}
