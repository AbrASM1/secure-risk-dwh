import json
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import oracledb
import polars as pl
import pytest

from srdwh.config import Profile
from srdwh.contracts.landing import EXPECTED, partition_folder
from tests.integration.db import rows
from tests.integration.pipeline import landing, named, retire, rewrite, run

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
GOLD_CHECKSUM = """
    SELECT f.as_of_date, count(*),
        sum(ora_hash(f.exposure_id || '|' || f.drawn_amt || '|' || c.cpty_id || '|' || c.rating))
    FROM srdwh_owner.gld_fact_exposure f JOIN srdwh_owner.gld_dim_counterparty c ON f.cpty_sk = c.cpty_sk
    WHERE f.as_of_date BETWEEN :first AND :last GROUP BY f.as_of_date ORDER BY 1"""
GOLD_STATE = """
    SELECT TO_CHAR(s.as_of_date, 'YYYY-MM-DD'), s.gld_cpty_load_id - s.slv_cpty_load_id,
        s.gld_expo_load_id - s.slv_expo_load_id,
        (SELECT count(*) FROM srdwh_owner.slv_exposure x WHERE x.as_of_date = s.as_of_date),
        (SELECT count(*) FROM srdwh_owner.gld_fact_exposure f WHERE f.as_of_date = s.as_of_date)
    FROM srdwh_owner.ops_asof_state s WHERE s.as_of_date BETWEEN :first AND :last ORDER BY 1"""


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


def window(profile: Profile) -> dict[str, object]:
    return {"first": profile.first_as_of, "last": profile.as_of_dates[-1]}


def test_rerun_noop(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    system_connection: oracledb.Connection,
    pipeline_profile: Callable[[int], Profile],
) -> None:
    profile = pipeline_profile(3)
    code, events = run(landing(tmp_path, profile), capsys, monkeypatch)
    assert code == 0
    assert [e["as_of"] for e in named(events, "gold_end")] == [d.isoformat() for d in profile.as_of_dates]
    gold = rows(system_connection, GOLD_CHECKSUM, **window(profile))
    assert len(gold) == 3
    code, events = run(tmp_path, capsys, monkeypatch)
    assert code == 0
    assert (len(named(events, "load_skipped")), named(events, "silver_end"), named(events, "gold_end")) == (6, [], [])
    assert rows(system_connection, GOLD_CHECKSUM, **window(profile)) == gold


def test_interrupted_run_resumes(
    tmp_path: Path,
    system_connection: oracledb.Connection,
    pipeline_profile: Callable[[int], Profile],
) -> None:
    profile = pipeline_profile(3)
    landing(tmp_path, profile)
    command = [str(Path(sys.executable).parent / "srdwh"), "run", "--profile", "ci", "--data-dir", str(tmp_path)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
    assert process.stdout is not None
    for line in process.stdout:
        if json.loads(line)["event"] == "gold_end":
            process.send_signal(signal.SIGKILL)
            break
    process.wait(timeout=60)
    rerun = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    assert rerun.returncode == 0, rerun.stdout
    state = rows(system_connection, GOLD_STATE, **window(profile))
    assert state == [
        (day.isoformat(), 0, 0, silver, silver)
        for day, (_, _, _, silver, _) in zip(profile.as_of_dates, state, strict=True)
    ]


REJECTS = {
    "counterparty": "SELECT src_row, reason_code FROM srdwh_owner.slv_rej_counterparty WHERE load_id = :load_id",
    "exposure": "SELECT src_row, reason_code FROM srdwh_owner.slv_rej_exposure WHERE load_id = :load_id",
}
LEAKED = {
    "counterparty": "SELECT count(*) FROM srdwh_owner.slv_counterparty s JOIN srdwh_owner.slv_rej_counterparty r "
    "ON r.load_id = s.load_id AND r.src_row = s.src_row WHERE s.load_id = :load_id",
    "exposure": "SELECT count(*) FROM srdwh_owner.slv_exposure s JOIN srdwh_owner.slv_rej_exposure r "
    "ON r.load_id = s.load_id AND r.src_row = s.src_row WHERE s.load_id = :load_id",
}
DIMENSION = """
    SELECT count(*), sum(ora_hash(cpty_id || '|' || segment_code || '|' || rating || '|' || default_flag || '|'
        || cpty_name || '|' || lei || '|' || country || '|' || valid_from || '|' || valid_to || '|' || is_current))
    FROM srdwh_owner.gld_dim_counterparty WHERE valid_to > :first"""
FACTS = """
    SELECT f.as_of_date, count(*), sum(ora_hash(f.exposure_id || '|' || f.segment_code || '|' || f.drawn_amt || '|'
        || f.undrawn_amt || '|' || f.collateral_amt || '|' || f.collateral_type || '|' || c.cpty_id || '|'
        || c.valid_from || '|' || p.product_code || '|' || d.calendar_date))
    FROM srdwh_owner.gld_fact_exposure f
    JOIN srdwh_owner.gld_dim_counterparty c ON f.cpty_sk = c.cpty_sk
    JOIN srdwh_owner.gld_dim_product p ON f.product_sk = p.product_sk
    JOIN srdwh_owner.gld_dim_date d ON f.date_sk = d.date_sk
    WHERE f.as_of_date BETWEEN :first AND :last GROUP BY f.as_of_date ORDER BY 1"""


def checksums(connection: oracledb.Connection, profile: Profile) -> tuple[object, ...]:
    window = {"first": profile.first_as_of, "last": profile.as_of_dates[-1]}
    return rows(connection, DIMENSION, first=profile.first_as_of)[0], tuple(rows(connection, FACTS, **window))


def downgrade(frame: pl.DataFrame) -> pl.DataFrame:
    changed = (pl.int_range(pl.len()) % 7 == 0) & (pl.col("rating") == "BBB")
    return frame.with_columns(pl.when(changed).then(pl.lit("BB")).otherwise(pl.col("rating")).alias("rating"))


def test_ground_truth_rejects(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    system_connection: oracledb.Connection,
    pipeline_profile: Callable[[int], Profile],
) -> None:
    profile = pipeline_profile(3)
    code, events = run(landing(tmp_path, profile), capsys, monkeypatch)
    assert code == 0
    for event in named(events, "load_end"):
        feed, as_of = str(event["feed"]), profile.first_as_of.fromisoformat(str(event["as_of"]))
        expected = pl.read_parquet(tmp_path / "ground_truth" / partition_folder(feed, as_of) / EXPECTED)
        stored = sorted(
            (int(str(r)), str(c)) for r, c in rows(system_connection, REJECTS[feed], load_id=event["load_id"])
        )
        assert stored == sorted(expected.rows()), (feed, as_of)
        assert rows(system_connection, LEAKED[feed], load_id=event["load_id"]) == [(0,)]
    assert len(named(events, "gold_end")) == 3


def test_rebuild_from_equals_full_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    system_connection: oracledb.Connection,
    pipeline_profile: Callable[[int], Profile],
) -> None:
    profile = pipeline_profile(3)
    assert run(landing(tmp_path, profile), capsys, monkeypatch)[0] == 0
    full = checksums(system_connection, profile)
    code, events = run(tmp_path, capsys, monkeypatch, "--rebuild-from", profile.first_as_of.isoformat())
    assert code == 0
    days = [d.isoformat() for d in profile.as_of_dates]
    assert [e["as_of"] for e in named(events, "silver_end") if e["as_of"] in days] == days
    assert [e["as_of"] for e in named(events, "gold_end") if e["as_of"] in days] == days
    assert checksums(system_connection, profile) == full


def test_late_correction_equals_full_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    system_connection: oracledb.Connection,
    pipeline_profile: Callable[[int], Profile],
) -> None:
    profile = pipeline_profile(3)
    assert run(landing(tmp_path, profile), capsys, monkeypatch)[0] == 0
    rewrite(tmp_path, "counterparty", profile.first_as_of, downgrade)
    code, events = run(tmp_path, capsys, monkeypatch)
    assert code == 0
    assert [e["as_of"] for e in named(events, "rewind_end")] == [profile.first_as_of.isoformat()]
    corrected = checksums(system_connection, profile)
    retire(system_connection, profile)
    code, events = run(tmp_path, capsys, monkeypatch)
    assert code == 0
    assert len(named(events, "load_end")) == 6
    assert checksums(system_connection, profile) == corrected
