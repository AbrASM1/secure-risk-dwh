import shutil
from collections.abc import Callable
from pathlib import Path

import oracledb
import polars as pl
import pytest

from srdwh.config import Profile
from srdwh.contracts.landing import partition_folder
from tests.integration.db import rows
from tests.integration.pipeline import landing, named, rewrite, run

pytestmark = pytest.mark.db
SILVER_CHECKSUM = """
    SELECT 'C', as_of_date, count(*), sum(ora_hash(cpty_id || '|' || cpty_name || '|' || rating || '|' || load_id))
    FROM srdwh_owner.slv_counterparty GROUP BY as_of_date
    UNION ALL
    SELECT 'E', as_of_date, count(*),
        sum(ora_hash(exposure_id || '|' || drawn_amt || '|' || collateral_amt || '|' || load_id))
    FROM srdwh_owner.slv_exposure GROUP BY as_of_date
    ORDER BY 1, 2"""
STATE = "SELECT as_of_date, slv_cpty_load_id, slv_expo_load_id FROM srdwh_owner.ops_asof_state ORDER BY 1"


def degrade(frame: pl.DataFrame) -> pl.DataFrame:
    usd = pl.int_range(pl.len()) % 10 == 0
    return frame.with_columns(pl.when(usd).then(pl.lit("USD")).otherwise(pl.col("currency")).alias("currency"))


def correct(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.when(pl.int_range(pl.len()) == 0).then(pl.lit("1.00")).otherwise(pl.col("drawn_amt")).alias("drawn_amt")
    )


def test_silver_built_then_rerun_replaces_nothing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    system_connection: oracledb.Connection,
    pipeline_profile: Callable[[int], Profile],
) -> None:
    profile = pipeline_profile(1)
    code, events = run(landing(tmp_path, profile), capsys, monkeypatch)
    assert code == 0
    loads = {e["feed"]: e["load_id"] for e in named(events, "load_end")}
    assert [
        (e["as_of"], e["rows"]) for e in named(events, "silver_end") if e["as_of"] == profile.first_as_of.isoformat()
    ]
    state = rows(
        system_connection,
        "SELECT slv_cpty_load_id, slv_expo_load_id FROM srdwh_owner.ops_asof_state WHERE as_of_date = :day",
        day=profile.first_as_of,
    )
    assert state == [(loads["counterparty"], loads["exposure"])]
    code, events = run(tmp_path, capsys, monkeypatch)
    assert code == 0
    assert named(events, "silver_end") == []
    assert named(events, "plan")[0]["rows"] == 0


def test_dq_breach_exit_2(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    system_connection: oracledb.Connection,
    pipeline_profile: Callable[[int], Profile],
) -> None:
    profile = pipeline_profile(1)
    assert run(landing(tmp_path, profile), capsys, monkeypatch)[0] == 0
    silver, state = rows(system_connection, SILVER_CHECKSUM), rows(system_connection, STATE)
    original = pl.read_parquet(
        tmp_path / "landing" / partition_folder("exposure", profile.first_as_of) / "part-0.parquet"
    )
    rewrite(tmp_path, "exposure", profile.first_as_of, degrade)
    code, events = run(tmp_path, capsys, monkeypatch)
    assert code == 2
    (breach,) = named(events, "threshold_breach")
    assert (breach["feed"], breach["as_of"]) == ("exposure", profile.first_as_of.isoformat())
    assert float(str(breach["reject_rate"])) > 0.05
    assert named(events, "silver_end") == []
    assert (events[-1]["event"], events[-1]["exit_code"]) == ("run_end", 2)
    assert rows(system_connection, SILVER_CHECKSUM) == silver
    assert rows(system_connection, STATE) == state
    kept = rows(
        system_connection,
        "SELECT r.rows_rejected, (SELECT count(*) FROM srdwh_owner.slv_rej_exposure j WHERE j.load_id = r.load_id) "
        "FROM srdwh_owner.ops_load_registry r WHERE r.load_id = :load_id",
        load_id=breach["load_id"],
    )
    assert kept[0][0] == kept[0][1]
    assert int(str(kept[0][0])) > 0
    rewrite(tmp_path, "exposure", profile.first_as_of, lambda _: correct(original))
    code, events = run(tmp_path, capsys, monkeypatch)
    assert code == 0
    assert [e["as_of"] for e in named(events, "silver_end")] == [profile.first_as_of.isoformat()]


def test_missing_feed_exit_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    pipeline_profile: Callable[[int], Profile],
) -> None:
    profile = pipeline_profile(1)
    landing(tmp_path, profile)
    held = tmp_path / "held"
    shutil.move(tmp_path / "landing" / partition_folder("exposure", profile.first_as_of), held)
    code, events = run(tmp_path, capsys, monkeypatch)
    assert code == 1
    assert f"a feed is missing for as_of {profile.first_as_of.isoformat()}" in str(named(events, "error")[0]["message"])
    shutil.move(held, tmp_path / "landing" / partition_folder("exposure", profile.first_as_of))
    assert run(tmp_path, capsys, monkeypatch)[0] == 0
