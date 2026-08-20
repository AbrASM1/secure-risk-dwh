import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import oracledb
import polars as pl
import pytest

from srdwh.config import Profile
from srdwh.contracts.landing import DATA_FILE, MANIFEST, partition_folder
from srdwh.ingest.registry import function
from tests.integration.db import Connect, rows
from tests.integration.pipeline import landing, named, run

pytestmark = pytest.mark.db


@dataclass(frozen=True)
class Delivery:
    data_dir: Path
    profile: Profile

    @property
    def first(self) -> str:
        return str(partition_folder("counterparty", self.profile.first_as_of))

    @property
    def second(self) -> str:
        return str(partition_folder("exposure", self.profile.first_as_of))

    def manifest(self, folder: str) -> dict[str, object]:
        return dict(json.loads((self.data_dir / "landing" / folder / MANIFEST).read_text(encoding="utf-8")))

    def manifests(self) -> list[dict[str, object]]:
        paths = sorted(self.data_dir.glob("landing/*/*/manifest.json"))
        return [json.loads(path.read_text(encoding="utf-8")) for path in paths]


@pytest.fixture
def delivery(tmp_path: Path, pipeline_profile: Callable[[int], Profile]) -> Delivery:
    profile = pipeline_profile(3)
    return Delivery(landing(tmp_path, profile), profile)


def registry(connection: oracledb.Connection, sha256: object) -> list[tuple[object, ...]]:
    return rows(
        connection,
        "SELECT status, rows_expected, rows_loaded FROM srdwh_owner.ops_load_registry "
        "WHERE sha256 = :sha ORDER BY load_id",
        sha=sha256,
    )


def test_loaded_file_skipped(
    delivery: Delivery,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    system_connection: oracledb.Connection,
) -> None:
    code, events = run(delivery.data_dir, capsys, monkeypatch)
    assert code == 0
    assert len(named(events, "load_end")) == 6
    assert (events[-1]["event"], events[-1]["exit_code"]) == ("run_end", 0)
    for manifest in delivery.manifests():
        assert registry(system_connection, manifest["sha256"]) == [("LOADED", manifest["rows"], manifest["rows"])]
    code, events = run(delivery.data_dir, capsys, monkeypatch)
    assert code == 0
    assert (len(named(events, "load_skipped")), named(events, "load_end")) == (6, [])
    assert all(len(registry(system_connection, m["sha256"])) == 1 for m in delivery.manifests())


def test_partition_without_manifest_skipped(
    delivery: Delivery,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    system_connection: oracledb.Connection,
) -> None:
    held = delivery.manifest(delivery.second)
    path = delivery.data_dir / "landing" / delivery.second / MANIFEST
    path.unlink()
    code, events = run(delivery.data_dir, capsys, monkeypatch)
    as_of = delivery.profile.first_as_of.isoformat()
    assert [(e["feed"], e["as_of"]) for e in named(events, "partition_not_ready")] == [("exposure", as_of)]
    assert len(named(events, "load_end")) == 5
    assert registry(system_connection, held["sha256"]) == []
    assert code == 1
    assert f"a feed is missing for as_of {as_of}" in str(named(events, "error")[0]["message"])
    path.write_text(json.dumps(held, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert run(delivery.data_dir, capsys, monkeypatch)[0] == 0


def test_structural_check_exit_1(
    delivery: Delivery,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    system_connection: oracledb.Connection,
) -> None:
    path = delivery.data_dir / "landing" / delivery.second / MANIFEST
    tampered = json.loads(path.read_text(encoding="utf-8")) | {"sha256": "f" * 64}
    path.write_text(json.dumps(tampered), encoding="utf-8")
    code, events = run(delivery.data_dir, capsys, monkeypatch)
    assert code == 1
    (failure,) = named(events, "structural_check_failed")
    assert failure["message"] == f"{delivery.second}/{DATA_FILE}: sha256 differs from the manifest"
    assert len(named(events, "load_end")) == 1
    assert registry(system_connection, "f" * 64) == []
    assert (events[-1]["event"], events[-1]["exit_code"]) == ("run_end", 1)


def test_failed_load_retried(
    delivery: Delivery,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    connect: Connect,
    system_connection: oracledb.Connection,
) -> None:
    first = delivery.manifest(delivery.first)
    with connect("SRDWH_ETL") as connection:
        day = delivery.profile.first_as_of
        function(connection, "register_load", None, "counterparty", day, "probe", first["sha256"], first["rows"])
        connection.commit()
    code, _ = run(delivery.data_dir, capsys, monkeypatch)
    assert code == 0
    assert [status for status, *_ in registry(system_connection, first["sha256"])] == ["FAILED", "LOADED"]


def test_bronze_rows_as_delivered(
    delivery: Delivery,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    system_connection: oracledb.Connection,
) -> None:
    code, events = run(delivery.data_dir, capsys, monkeypatch)
    assert code == 0
    load_id = named(events, "load_end")[0]["load_id"]
    file_path = f"{delivery.first}/{DATA_FILE}"
    delivered = pl.read_parquet(delivery.data_dir / "landing" / file_path)
    stored = rows(
        system_connection,
        "SELECT src_row, cpty_id, lei, src_file, TO_CHAR(ingested_at, 'TZH:TZM') "
        "FROM srdwh_owner.brz_counterparty WHERE load_id = :load_id ORDER BY src_row",
        load_id=load_id,
    )
    assert [row[0] for row in stored] == list(range(1, delivered.height + 1))
    assert [row[1] or "" for row in stored] == delivered["cpty_id"].to_list()
    assert [row[2] or "" for row in stored] == delivered["lei"].to_list()
    assert {row[3] for row in stored} == {file_path}
    assert {row[4] for row in stored} == {"+00:00"}
