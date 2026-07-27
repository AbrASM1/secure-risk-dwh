from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path

import oracledb
import pytest

from tests.integration.db import execute, rows

pytestmark = pytest.mark.db
CHECK = Path(__file__).resolve().parents[2] / "db" / "ddl" / "99_deploy_check.sql"


def run_check(connection: oracledb.Connection) -> None:
    execute(connection, CHECK.read_text(encoding="utf-8").split("\n", 1)[1].strip().removesuffix("/").strip())


@pytest.fixture
def probe(system_connection: oracledb.Connection) -> Iterator[oracledb.Connection]:
    yield system_connection
    for statement in ("DROP VIEW srdwh_owner.v_deploy_probe", "DROP TABLE srdwh_owner.deploy_probe PURGE"):
        with suppress(oracledb.DatabaseError):
            execute(system_connection, statement)


def test_no_invalid_object(system_connection: oracledb.Connection) -> None:
    assert (
        rows(
            system_connection,
            "SELECT owner, object_name FROM dba_objects "
            "WHERE owner IN ('SRDWH_OWNER', 'SRDWH_SEC') AND status != 'VALID'",
        )
        == []
    )
    assert (
        rows(system_connection, "SELECT owner, name FROM dba_errors WHERE owner IN ('SRDWH_OWNER', 'SRDWH_SEC')") == []
    )


def test_every_column_commented(system_connection: oracledb.Connection) -> None:
    assert (
        rows(
            system_connection,
            "SELECT table_name FROM dba_tab_comments WHERE owner IN ('SRDWH_OWNER', 'SRDWH_SEC') AND comments IS NULL",
        )
        == []
    )
    assert (
        rows(
            system_connection,
            "SELECT table_name FROM dba_col_comments WHERE owner IN ('SRDWH_OWNER', 'SRDWH_SEC') AND comments IS NULL",
        )
        == []
    )


def test_deploy_check_passes(system_connection: oracledb.Connection) -> None:
    run_check(system_connection)


def test_deploy_check_rejects_uncommented_and_invalid_objects(probe: oracledb.Connection) -> None:
    execute(probe, "CREATE TABLE srdwh_owner.deploy_probe (probe_id NUMBER)")
    execute(probe, "COMMENT ON TABLE srdwh_owner.deploy_probe IS 'Deploy check probe.'")
    with pytest.raises(
        oracledb.DatabaseError, match=r"ORA-20001: deploy check: no comment on SRDWH_OWNER\.DEPLOY_PROBE\.PROBE_ID"
    ):
        run_check(probe)
    execute(probe, "COMMENT ON COLUMN srdwh_owner.deploy_probe.probe_id IS 'Probe column.'")
    run_check(probe)
    execute(
        probe, "CREATE FORCE VIEW srdwh_owner.v_deploy_probe AS SELECT missing_column FROM srdwh_owner.deploy_probe"
    )
    with pytest.raises(oracledb.DatabaseError, match=r"invalid SRDWH_OWNER\.V_DEPLOY_PROBE"):
        run_check(probe)
