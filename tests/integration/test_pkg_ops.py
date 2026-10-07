import os
from collections.abc import Iterator
from datetime import date

import oracledb
import pytest

from tests.integration.db import Connect, execute, rows

pytestmark = pytest.mark.db
TEST_RUN_ID = -1001
AS_OF = date(2025, 1, 31)


@pytest.fixture
def owner() -> Iterator[oracledb.Connection]:
    connection = oracledb.connect(user="system", password=os.environ["ORACLE_PASSWORD"], dsn=os.environ["SRDWH_DSN"])
    yield connection
    connection.rollback()
    execute(connection, "DELETE FROM srdwh_owner.ops_err_log WHERE run_id = :run_id", run_id=TEST_RUN_ID)
    connection.commit()
    connection.close()


def register(connection: oracledb.Connection, feed: str, rows_expected: int) -> int:
    with connection.cursor() as cursor:
        load_id = cursor.callfunc(
            "srdwh_owner.pkg_ops.register_load",
            int,
            [TEST_RUN_ID, feed, AS_OF, f"{feed}/as_of_date=2025-01-31/part-0.parquet", "0" * 64, rows_expected],
        )
    return int(load_id)


def call(connection: oracledb.Connection, procedure: str, *arguments: object) -> None:
    with connection.cursor() as cursor:
        cursor.callproc(f"srdwh_owner.pkg_ops.{procedure}", [TEST_RUN_ID, *arguments])


def load_state(connection: oracledb.Connection, load_id: int) -> tuple[object, ...]:
    return rows(
        connection,
        "SELECT status, rows_loaded, message, CASE WHEN ended_at IS NULL THEN 'open' ELSE 'closed' END "
        "FROM srdwh_owner.ops_load_registry WHERE load_id = :load_id",
        load_id=load_id,
    )[0]


def add_bronze_rows(connection: oracledb.Connection, load_id: int, count: int) -> None:
    with connection.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO srdwh_owner.brz_counterparty (cpty_id, load_id, src_file, src_row) VALUES (:1, :2, :3, :4)",
            [(f"CP{row:08d}", load_id, "probe", row) for row in range(1, count + 1)],
        )


def test_register_then_close_load_loaded(owner: oracledb.Connection) -> None:
    load_id = register(owner, "counterparty", 2)
    assert load_state(owner, load_id) == ("STARTED", None, None, "open")
    add_bronze_rows(owner, load_id, 2)
    call(owner, "close_load", load_id)
    assert load_state(owner, load_id) == ("LOADED", 2, None, "closed")


def test_close_load_short_of_manifest_fails(owner: oracledb.Connection) -> None:
    load_id = register(owner, "counterparty", 3)
    add_bronze_rows(owner, load_id, 2)
    call(owner, "close_load", load_id)
    assert load_state(owner, load_id) == ("FAILED", 2, "bronze holds 2 rows, manifest announces 3", "closed")


def test_closing_a_closed_load_raises_and_logs(owner: oracledb.Connection) -> None:
    load_id = register(owner, "exposure", 0)
    call(owner, "close_load", load_id)
    with pytest.raises(oracledb.DatabaseError, match="ORA-20103"):
        call(owner, "close_load", load_id)
    owner.rollback()
    logged = rows(
        owner, "SELECT step, sql_code FROM srdwh_owner.ops_err_log WHERE run_id = :run_id", run_id=TEST_RUN_ID
    )
    assert logged == [("close_load", -20103)]


def test_fail_orphan_loads_and_fail_load(owner: oracledb.Connection) -> None:
    orphans = [register(owner, "counterparty", 1), register(owner, "exposure", 1)]
    call(owner, "fail_orphan_loads")
    assert {load_state(owner, load_id)[0] for load_id in orphans} == {"FAILED"}
    failed = register(owner, "exposure", 5)
    call(owner, "fail_load", failed, "direct path load raised DPY-1234")
    assert load_state(owner, failed)[:3] == ("FAILED", None, "direct path load raised DPY-1234")


def test_start_run_and_log_step(owner: oracledb.Connection) -> None:
    with owner.cursor() as cursor:
        first = cursor.callfunc("srdwh_owner.pkg_ops.start_run", int)
        second = cursor.callfunc("srdwh_owner.pkg_ops.start_run", int)
        assert second > first
        cursor.callproc(
            "srdwh_owner.pkg_ops.log_step",
            [second, "ingest", AS_OF, 1500, 10, 9, 1, "OK", None],
        )
    logged = rows(
        owner,
        "SELECT step, TO_CHAR(as_of_date, 'YYYY-MM-DD'), rows_in, rows_out, rows_rejected, status, "
        "TO_CHAR(started_at, 'TZH:TZM'), TO_CHAR(ended_at, 'TZH:TZM'), "
        "EXTRACT(SECOND FROM (ended_at - started_at)) + 60 * EXTRACT(MINUTE FROM (ended_at - started_at)) "
        "+ 3600 * EXTRACT(HOUR FROM (ended_at - started_at)) "
        "FROM srdwh_owner.ops_run_log WHERE run_id = :run_id",
        run_id=second,
    )
    assert logged == [("ingest", AS_OF.isoformat(), 10, 9, 1, "OK", "+00:00", "+00:00", 1.5)]


def test_pkg_err_logs_autonomously_and_caller_reraises(owner: oracledb.Connection) -> None:
    block = (
        "BEGIN raise_application_error(-20999, 'probe failure'); "
        "EXCEPTION WHEN OTHERS THEN srdwh_owner.pkg_err.log_error(:run_id, 'probe'); RAISE; END;"
    )
    with pytest.raises(oracledb.DatabaseError, match="ORA-20999"):
        execute(owner, block, run_id=TEST_RUN_ID)
    owner.rollback()
    logged = rows(
        owner,
        "SELECT step, sql_code, message, CASE WHEN backtrace LIKE 'ORA-06512%' THEN 'traced' END "
        "FROM srdwh_owner.ops_err_log WHERE run_id = :run_id",
        run_id=TEST_RUN_ID,
    )
    assert logged == [("probe", -20999, "ORA-20999: probe failure", "traced")]


def test_run_lock_is_exclusive_per_session(connect: Connect) -> None:
    first, second = connect("SRDWH_ETL"), connect("SRDWH_ETL")
    with first.cursor() as cursor:
        cursor.callproc("srdwh_owner.pkg_ops.lock_run")
        cursor.callproc("srdwh_owner.pkg_ops.lock_run")
    with pytest.raises(oracledb.DatabaseError, match="ORA-20101"), second.cursor() as cursor:
        cursor.callproc("srdwh_owner.pkg_ops.lock_run")
    first.close()
    with second.cursor() as cursor:
        cursor.callproc("srdwh_owner.pkg_ops.lock_run")
    second.close()


def test_etl_executes_pkg_ops_but_not_pkg_err(connect: Connect) -> None:
    with connect("SRDWH_ETL") as connection, connection.cursor() as cursor:
        assert cursor.callfunc("srdwh_owner.pkg_ops.start_run", int) > 0
        with pytest.raises(oracledb.DatabaseError, match="PLS-00201"):
            cursor.execute("BEGIN srdwh_owner.pkg_err.log_error(NULL, 'probe'); END;")
