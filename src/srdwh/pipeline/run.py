import sys
import time
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TextIO

import oracledb

from srdwh.config import Settings, credentials
from srdwh.db import connect, tag
from srdwh.ingest.landing import Partition, StructuralError, partitions, read_delivery
from srdwh.ingest.load import load
from srdwh.ingest.registry import call, function, is_loaded
from srdwh.log import Event, emit, run_end
from srdwh.pipeline import gold, silver

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_BREACH = 2
LOCK_BUSY = 20101
FAILURES = (ValueError, OSError, oracledb.Error)
RUN_STATUS = {EXIT_OK: "OK", EXIT_FAILURE: "FAILED", EXIT_BREACH: "BREACH"}


class LoadError(ValueError):
    pass


@dataclass(frozen=True)
class RunOptions:
    settings: Settings
    data_dir: Path
    rebuild_from: date | None = None


def run(options: RunOptions, stream: TextIO | None = None) -> int:
    started, out = time.monotonic(), stream or sys.stdout
    run_id, code = None, EXIT_FAILURE
    try:
        with connect(credentials("SRDWH_ETL"), None, "lock") as connection:
            run_id, code = _locked(connection, options, out)
    except FAILURES as error:
        _report(out, run_id, "run", error)
    run_end(run_id, code, _elapsed_ms(started), out)
    return code


def ingest(connection: oracledb.Connection, run_id: int, settings: Settings, landing: Path, stream: TextIO) -> None:
    for partition in partitions(landing):
        tag(connection, run_id, "ingest")
        _ingest_partition(connection, run_id, settings.batch_size, partition, stream)


def _locked(connection: oracledb.Connection, options: RunOptions, stream: TextIO) -> tuple[int | None, int]:
    try:
        call(connection, "lock_run")
    except oracledb.DatabaseError as error:
        if error.args[0].code != LOCK_BUSY:
            raise
        emit(Event("lock_busy", "lock", level="ERROR", message="another run holds the run lock"), stream)
        return None, EXIT_FAILURE
    run_id = function(connection, "start_run")
    return run_id, _body(connection, run_id, options, stream)


def _body(connection: oracledb.Connection, run_id: int, options: RunOptions, stream: TextIO) -> int:
    started_at = datetime.now(UTC)
    tag(connection, run_id, "run")
    emit(Event("run_start", "run", run_id=run_id), stream)
    try:
        call(connection, "fail_orphan_loads", run_id)
        connection.commit()
        ingest(connection, run_id, options.settings, options.data_dir / "landing", stream)
        code = _phases(connection, run_id, options, stream)
    except FAILURES as error:
        connection.rollback()
        _report(stream, run_id, "run", error)
        code = EXIT_FAILURE
    _log_step(connection, run_id, "run", None, started_at, None, RUN_STATUS[code])
    return code


def _phases(connection: oracledb.Connection, run_id: int, options: RunOptions, stream: TextIO) -> int:
    tag(connection, run_id, "plan")
    work = silver.plan(connection, options.rebuild_from)
    emit(Event("plan", "plan", run_id=run_id, rows=len(work)), stream)
    threshold = options.settings.reject_threshold
    breached = [silver.reject(connection, run_id, item, threshold, stream) for item in work]
    if any(breached):
        return EXIT_BREACH
    for item in work:
        silver.replace(connection, run_id, item, stream)
    if work:
        gold.gather_stats(connection, run_id, gold.SILVER_TABLES)
    gold.gold(connection, run_id, options.rebuild_from, stream)
    return EXIT_OK


def _ingest_partition(
    connection: oracledb.Connection, run_id: int, batch_size: int, partition: Partition, stream: TextIO
) -> None:
    if not partition.ready:
        emit(_partition_event("partition_not_ready", partition, run_id, "WARNING"), stream)
        return
    delivery = read_delivery(partition)
    if is_loaded(connection, partition.feed, partition.as_of, delivery.sha256):
        emit(_partition_event("load_skipped", partition, run_id), stream)
        return
    started, started_at = time.monotonic(), datetime.now(UTC)
    result = load(connection, run_id, delivery, batch_size)
    status = "OK" if result.status == "LOADED" else "FAILED"
    _log_step(connection, run_id, "ingest", partition, started_at, (delivery.frame.height, result.rows_loaded), status)
    loaded = _partition_event("load_end", partition, run_id, "INFO" if status == "OK" else "ERROR")
    emit(replace(loaded, load_id=result.load_id, rows=result.rows_loaded, duration_ms=_elapsed_ms(started)), stream)
    if status != "OK":
        raise LoadError(f"{partition.file_path}: load {result.load_id} ended {result.status}")


def _partition_event(event: str, partition: Partition, run_id: int, level: str = "INFO") -> Event:
    return Event(event, "ingest", level=level, run_id=run_id, as_of=partition.as_of, feed=partition.feed)


def _log_step(
    connection: oracledb.Connection,
    run_id: int,
    step: str,
    partition: Partition | None,
    started_at: datetime,
    rows: tuple[int, int | None] | None,
    status: str,
) -> None:
    rows_in, rows_out = rows or (None, None)
    as_of = partition.as_of if partition else None
    call(connection, "log_step", run_id, step, as_of, started_at, rows_in, rows_out, None, status, None)
    connection.commit()


def _report(stream: TextIO, run_id: int | None, step: str, error: Exception) -> None:
    event = "structural_check_failed" if isinstance(error, StructuralError) else "error"
    message = str(error).splitlines()[0] if str(error) else type(error).__name__
    emit(Event(event, step, level="ERROR", run_id=run_id, message=message), stream)


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)
