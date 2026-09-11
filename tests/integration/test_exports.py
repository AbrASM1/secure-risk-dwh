from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import oracledb
import polars as pl
import pytest

from srdwh.config import Profile
from srdwh.export.views import QUERIES, export_path
from tests.integration.db import rows
from tests.integration.pipeline import identities, landing, named, run

pytestmark = pytest.mark.db
FACT_RWA = (
    "SELECT TO_CHAR(sum(rwa), 'FM99999999999999999999999990.00') FROM srdwh_owner.gld_fact_rwa "
    "WHERE as_of_date = :as_of"
)
GOLD_RECORDED = "SELECT gld_at FROM srdwh_owner.ops_asof_state WHERE as_of_date = :as_of"


def exported(data_dir: Path) -> dict[Path, tuple[bytes, int]]:
    files = (path for path in (data_dir / "exports").rglob("*") if path.is_file())
    return {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}


def test_parquet_decimal(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    system_connection: oracledb.Connection,
    pipeline_profile: Callable[[int], Profile],
) -> None:
    profile = pipeline_profile(2)
    assert run(landing(tmp_path, profile), capsys, monkeypatch)[0] == 0
    for as_of in profile.as_of_dates:
        frames = {view: pl.read_parquet(export_path(tmp_path / "exports", view, as_of)) for view in QUERIES}
        assert [name for frame in frames.values() for name, dtype in frame.schema.items() if dtype.is_float()] == []
        assert all(set(frame["as_of_date"]) == {as_of} for frame in frames.values())
        by_class, trend, top = frames["v_rwa_by_class"], frames["v_rwa_trend"], frames["v_top_exposures"]
        assert (by_class.schema["rwea"], by_class.schema["exposure_value"]) == (pl.Decimal(28, 2), pl.Decimal(30, 6))
        assert (trend.schema["rwa_density"], top.schema["rwa"]) == (pl.Decimal(30, 6), pl.Decimal(20, 2))
        assert by_class["rwea"].sum() == Decimal(str(rows(system_connection, FACT_RWA, as_of=as_of)[0][0]))
        assert top.height == 20


def test_atomic_rewrite(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    system_connection: oracledb.Connection,
    pipeline_profile: Callable[[int], Profile],
) -> None:
    profile = pipeline_profile(1)
    as_of = profile.first_as_of
    assert run(landing(tmp_path, profile), capsys, monkeypatch)[0] == 0
    before = exported(tmp_path)

    def full_disk(source: object, target: object) -> None:
        raise OSError(28, "No space left on device")

    with monkeypatch.context() as patch:
        patch.setattr("srdwh.files.os.replace", full_disk)
        code, events = run(tmp_path, capsys, monkeypatch, "--rebuild-from", as_of.isoformat())
    assert code == 1
    assert named(events, "export_end") == []
    assert exported(tmp_path) == before
    assert rows(system_connection, GOLD_RECORDED, as_of=as_of) == [(None,)]
    code, events = run(tmp_path, capsys, monkeypatch)
    assert code == 0
    assert [event["as_of"] for event in named(events, "export_end")] == [as_of.isoformat()]
    assert rows(system_connection, GOLD_RECORDED, as_of=as_of) != [(None,)]
    assert {path.name for path in exported(tmp_path)} == {path.name for path in before}


def test_no_name_in_exports(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    pipeline_profile: Callable[[int], Profile],
) -> None:
    profile = pipeline_profile(2)
    hidden = identities(landing(tmp_path, profile))
    assert run(tmp_path, capsys, monkeypatch)[0] == 0
    frames = [pl.read_parquet(path) for path in sorted((tmp_path / "exports").rglob("*.parquet"))]
    assert len(frames) == len(QUERIES) * 2
    assert all({"cpty_name", "lei"}.isdisjoint(frame.columns) for frame in frames)
    text = " ".join(frame.write_csv() for frame in frames)
    assert [value for value in hidden if value in text] == []
