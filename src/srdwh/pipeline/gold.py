import time
from datetime import date
from pathlib import Path
from typing import TextIO

import oracledb

from srdwh.db import tag
from srdwh.export.views import export_as_of
from srdwh.ingest.registry import call
from srdwh.log import Event, emit

OPS = "srdwh_owner.pkg_ops"
GOLD = "srdwh_owner.pkg_gold"
RWA = "srdwh_owner.pkg_rwa"
GOLD_TABLES = ("GLD_DIM_COUNTERPARTY", "GLD_FACT_EXPOSURE", "GLD_FACT_RWA", "GLD_MART_RWA")
SILVER_TABLES = ("SLV_COUNTERPARTY", "SLV_EXPOSURE", "SLV_REJ_COUNTERPARTY", "SLV_REJ_EXPOSURE")


def gold(
    connection: oracledb.Connection, run_id: int, rebuild_from: date | None, exports: Path, stream: TextIO
) -> None:
    tag(connection, run_id, "plan")
    start = _date(connection, "gold_start", rebuild_from)
    if start is None:
        return
    built = _date(connection, "gold_built_until")
    if built is not None and start <= built:
        _rewind(connection, run_id, start, stream)
    for as_of in _dates(connection, start):
        _build(connection, run_id, as_of, stream)
        _export(connection, run_id, as_of, exports, stream)
    gather_stats(connection, run_id, GOLD_TABLES)


def gather_stats(connection: oracledb.Connection, run_id: int, tables: tuple[str, ...]) -> None:
    tag(connection, run_id, "stats")
    for table in tables:
        call(connection, "gather_stats", run_id, table)


def _rewind(connection: oracledb.Connection, run_id: int, start: date, stream: TextIO) -> None:
    tag(connection, run_id, "rewind")
    started = time.monotonic()
    call(connection, "clear_gold", run_id, start)
    with connection.cursor() as cursor:
        cursor.callproc(f"{GOLD}.rewind", [run_id, start])
    call(connection, "log_step", run_id, "rewind", start, _ms(started), None, None, None, "OK", None)
    connection.commit()
    emit(Event("rewind_end", "rewind", run_id=run_id, as_of=start, duration_ms=_ms(started)), stream)


def _build(connection: oracledb.Connection, run_id: int, as_of: date, stream: TextIO) -> None:
    tag(connection, run_id, "gold")
    started = time.monotonic()
    with connection.cursor() as cursor:
        cursor.callproc(f"{GOLD}.build_as_of", [run_id, as_of])
        cursor.callproc(f"{RWA}.compute", [run_id, as_of])
        built = cursor.var(int)
        cursor.callproc(f"{GOLD}.finish_as_of", [run_id, as_of, built])
        rows = int(built.getvalue())
    call(connection, "log_step", run_id, "gold", as_of, _ms(started), None, rows, None, "OK", None)
    connection.commit()
    emit(Event("gold_end", "gold", run_id=run_id, as_of=as_of, rows=rows, duration_ms=_ms(started)), stream)


def _export(connection: oracledb.Connection, run_id: int, as_of: date, exports: Path, stream: TextIO) -> None:
    tag(connection, run_id, "export")
    started = time.monotonic()
    rows = export_as_of(connection, as_of, exports)
    call(connection, "log_step", run_id, "export", as_of, _ms(started), None, rows, None, "OK", None)
    call(connection, "record_gold", run_id, as_of)
    connection.commit()
    emit(Event("export_end", "export", run_id=run_id, as_of=as_of, rows=rows, duration_ms=_ms(started)), stream)


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
