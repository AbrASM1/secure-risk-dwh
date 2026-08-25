import hashlib
import itertools
import json
import secrets
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path

import oracledb
import polars as pl
import pytest

from srdwh.cli import main
from srdwh.config import Profile, load_settings, month_end
from srdwh.contracts.landing import DATA_FILE, MANIFEST, partition_folder
from srdwh.generate.landing import parquet, write_landing

SETTINGS = Path(__file__).resolve().parents[2] / "srdwh.toml"
REF = SETTINGS.parent / "db" / "ref"
Events = list[dict[str, object]]


_MONTHS = itertools.count(secrets.randbelow(60) * 2)
RETIRE = (
    "UPDATE srdwh_owner.ops_load_registry SET status = 'FAILED', message = 'retired by tests', "
    "ended_at = coalesce(ended_at, systimestamp) WHERE as_of_date = :day AND status IN ('STARTED', 'LOADED')",
    "DELETE FROM srdwh_owner.slv_exposure WHERE as_of_date = :day",
    "DELETE FROM srdwh_owner.slv_counterparty WHERE as_of_date = :day",
    "DELETE FROM srdwh_owner.ops_asof_state WHERE as_of_date = :day",
)


def unique_profile(as_of_count: int = 1) -> Profile:
    first = month_end(date(2030, 1, 31), next(_MONTHS))
    for _ in range(as_of_count - 1):
        next(_MONTHS)
    return replace(
        load_settings(SETTINGS).profile("ci"),
        seed=secrets.randbelow(10**9),
        first_as_of=first,
        as_of_count=as_of_count,
    )


def landing(data_dir: Path, profile: Profile) -> Path:
    write_landing(profile, REF, data_dir)
    return data_dir


def run(data_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> tuple[int, Events]:
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["srdwh", "run", "--profile", "ci", "--data-dir", str(data_dir)])
    with pytest.raises(SystemExit) as stop:
        main()
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    return int(str(stop.value.code)), events


def rewrite(data_dir: Path, feed: str, as_of: date, change: Callable[[pl.DataFrame], pl.DataFrame]) -> str:
    folder = data_dir / "landing" / partition_folder(feed, as_of)
    frame = change(pl.read_parquet(folder / DATA_FILE))
    data = parquet(frame)
    manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    manifest |= {"sha256": hashlib.sha256(data).hexdigest(), "rows": frame.height}
    (folder / MANIFEST).unlink()
    (folder / DATA_FILE).write_bytes(data)
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(manifest["sha256"])


def named(events: Events, event: str) -> Events:
    return [e for e in events if e["event"] == event]


def retire(connection: oracledb.Connection, profile: Profile) -> None:
    with connection.cursor() as cursor:
        cursor.callproc("srdwh_owner.pkg_ops.clear_gold", [None, profile.first_as_of])
        cursor.callproc("srdwh_owner.pkg_gold.rewind", [None, profile.first_as_of])
        for statement in RETIRE:
            cursor.executemany(statement, [{"day": day} for day in profile.as_of_dates])
    connection.commit()
