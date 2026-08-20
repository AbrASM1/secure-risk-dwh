import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TextIO

import oracledb

from srdwh.db import tag
from srdwh.ingest.registry import call
from srdwh.log import Event, emit

SILVER = "srdwh_owner.pkg_silver"


class MissingFeedError(ValueError):
    pass


@dataclass(frozen=True)
class SilverWork:
    as_of: date
    cpty_load_id: int
    expo_load_id: int


@dataclass(frozen=True)
class Rejects:
    feed: str
    load_id: int
    rows_loaded: int
    rows_rejected: int

    @property
    def rate(self) -> Decimal:
        return Decimal(self.rows_rejected) / Decimal(self.rows_loaded) if self.rows_loaded else Decimal(0)


def plan(connection: oracledb.Connection, rebuild_from: date | None) -> list[SilverWork]:
    with connection.cursor() as cursor:
        found = cursor.callfunc("srdwh_owner.pkg_ops.silver_plan", oracledb.DB_TYPE_CURSOR, [rebuild_from])
        rows = found.fetchall()
    missing = [day.date().isoformat() for day, cpty, expo in rows if cpty is None or expo is None]
    if missing:
        raise MissingFeedError(f"a feed is missing for as_of {', '.join(missing)}")
    return [SilverWork(day.date(), int(cpty), int(expo)) for day, cpty, expo in rows]


def reject(connection: oracledb.Connection, run_id: int, work: SilverWork, threshold: Decimal, stream: TextIO) -> bool:
    tag(connection, run_id, "rejects")
    started, started_at = time.monotonic(), datetime.now(UTC)
    _silver(connection, "reject_counterparties", run_id, work.cpty_load_id)
    counterparties = _rejects(connection, "counterparty", work.cpty_load_id)
    found = [counterparties]
    if counterparties.rate <= threshold:
        _silver(connection, "reject_exposures", run_id, work.expo_load_id, work.cpty_load_id)
        found.append(_rejects(connection, "exposure", work.expo_load_id))
    breached = [r for r in found if r.rate > threshold]
    status = "BREACH" if breached else "OK"
    loaded, rejected = sum(r.rows_loaded for r in found), sum(r.rows_rejected for r in found)
    call(connection, "log_step", run_id, "rejects", work.as_of, started_at, loaded, None, rejected, status, None)
    connection.commit()
    for found_rejects in found:
        emit(_rejects_event(run_id, work, found_rejects, threshold, started), stream)
    return bool(breached)


def replace(connection: oracledb.Connection, run_id: int, work: SilverWork, stream: TextIO) -> None:
    tag(connection, run_id, "silver")
    started, started_at = time.monotonic(), datetime.now(UTC)
    _silver(connection, "replace_as_of", run_id, work.cpty_load_id, work.expo_load_id)
    call(connection, "record_silver", run_id, work.as_of, work.cpty_load_id, work.expo_load_id)
    rows = _silver_rows(connection, work)
    call(connection, "log_step", run_id, "silver", work.as_of, started_at, None, rows, None, "OK", None)
    connection.commit()
    emit(Event("silver_end", "silver", run_id=run_id, as_of=work.as_of, rows=rows, duration_ms=_ms(started)), stream)


def _silver(connection: oracledb.Connection, procedure: str, *arguments: object) -> None:
    with connection.cursor() as cursor:
        cursor.callproc(f"{SILVER}.{procedure}", list(arguments))


def _rejects(connection: oracledb.Connection, feed: str, load_id: int) -> Rejects:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rows_loaded, rows_rejected FROM srdwh_owner.ops_load_registry WHERE load_id = :load_id",
            load_id=load_id,
        )
        loaded, rejected = cursor.fetchone()
    return Rejects(feed, load_id, int(loaded), int(rejected))


def _silver_rows(connection: oracledb.Connection, work: SilverWork) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT sum(rows_loaded - rows_rejected) FROM srdwh_owner.ops_load_registry "
            "WHERE load_id IN (:cpty_load_id, :expo_load_id)",
            cpty_load_id=work.cpty_load_id,
            expo_load_id=work.expo_load_id,
        )
        (rows,) = cursor.fetchone()
    return int(rows)


def _rejects_event(run_id: int, work: SilverWork, found: Rejects, threshold: Decimal, started: float) -> Event:
    breach = found.rate > threshold
    return Event(
        "threshold_breach" if breach else "rejects_end",
        "rejects",
        level="ERROR" if breach else "INFO",
        run_id=run_id,
        as_of=work.as_of,
        feed=found.feed,
        load_id=found.load_id,
        rows_rejected=found.rows_rejected,
        reject_rate=found.rate.quantize(Decimal("0.0001")),
        duration_ms=_ms(started),
    )


def _ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)
