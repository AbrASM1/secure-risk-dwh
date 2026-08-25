import time
from datetime import UTC, date, datetime
from typing import TextIO

import oracledb

from srdwh.db import tag
from srdwh.ingest.registry import call
from srdwh.log import Event, emit

OPS = "srdwh_owner.pkg_ops"
GOLD = "srdwh_owner.pkg_gold"
GOLD_TABLES = ("GLD_DIM_COUNTERPARTY", "GLD_FACT_EXPOSURE")
SILVER_TABLES = ("SLV_COUNTERPARTY", "SLV_EXPOSURE", "SLV_REJ_COUNTERPARTY", "SLV_REJ_EXPOSURE")


def gold(connection: oracledb.Connection, run_id: int, rebuild_from: date | None, stream: TextIO) -> None:
    tag(connection, run_id, "plan")
    start = _date(connection, "gold_start", rebuild_from)
    if start is None:
        return
    built = _date(connection, "gold_built_until")
    if built is not None and start <= built:
        _rewind(connection, run_id, start, stream)
    for as_of in _dates(connection, start):
        _build(connection, run_id, as_of, stream)
    gather_stats(connection, run_id, GOLD_TABLES)


def gather_stats(connection: oracledb.Connection, run_id: int, tables: tuple[str, ...]) -> None:
    tag(connection, run_id, "stats")
    for table in tables:
        call(connection, "gather_stats", run_id, table)


def _rewind(connection: oracledb.Connection, run_id: int, start: date, stream: TextIO) -> None:
    tag(connection, run_id, "rewind")
    started, started_at = time.monotonic(), datetime.now(UTC)
    call(connection, "clear_gold", run_id, start)
    with connection.cursor() as cursor:
        cursor.callproc(f"{GOLD}.rewind", [run_id, start])
    call(connection, "log_step", run_id, "rewind", start, started_at, None, None, None, "OK", None)
    connection.commit()
    emit(Event("rewind_end", "rewind", run_id=run_id, as_of=start, duration_ms=_ms(started)), stream)


def _build(connection: oracledb.Connection, run_id: int, as_of: date, stream: TextIO) -> None:
    tag(connection, run_id, "gold")
    started, started_at = time.monotonic(), datetime.now(UTC)
    with connection.cursor() as cursor:
        built = cursor.var(int)
        cursor.callproc(f"{GOLD}.build_as_of", [run_id, as_of, built])
        rows = int(built.getvalue())
    call(connection, "log_step", run_id, "gold", as_of, started_at, None, rows, None, "OK", None)
    connection.commit()
    call(connection, "record_gold", run_id, as_of)
    connection.commit()
    emit(Event("gold_end", "gold", run_id=run_id, as_of=as_of, rows=rows, duration_ms=_ms(started)), stream)


def _date(connection: oracledb.Connection, name: str, *arguments: object) -> date | None:
    with connection.cursor() as cursor:
        found = cursor.callfunc(f"{OPS}.{name}", oracledb.DB_TYPE_DATE, list(arguments))
    return None if found is None else found.date()


def _dates(connection: oracledb.Connection, start: date) -> list[date]:
    with connection.cursor() as cursor:
        found = cursor.callfunc(f"{OPS}.gold_dates", oracledb.DB_TYPE_CURSOR, [start])
        return [day.date() for (day,) in found.fetchall()]


def _ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)
