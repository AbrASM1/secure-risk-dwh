import oracledb
import pytest

pytestmark = pytest.mark.db


def scalar(connection: oracledb.Connection, sql: str) -> object:
    with connection.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
    assert row is not None
    return row[0]


def test_utplsql_version(system_connection: oracledb.Connection) -> None:
    source = scalar(
        system_connection,
        "SELECT text FROM dba_source"
        " WHERE owner = 'UT3' AND name = 'UT_UTILS' AND type = 'PACKAGE' AND text LIKE '%gc_version%'",
    )
    assert "'v.3.2.3." in str(source)


def test_utplsql_objects_valid(system_connection: oracledb.Connection) -> None:
    assert scalar(system_connection, "SELECT COUNT(*) FROM dba_objects WHERE owner = 'UT3' AND status <> 'VALID'") == 0


def test_ut3_account_locked(system_connection: oracledb.Connection) -> None:
    status = scalar(system_connection, "SELECT account_status FROM dba_users WHERE username = 'UT3'")
    assert "LOCKED" in str(status)


def test_utplsql_not_exposed_to_public(system_connection: oracledb.Connection) -> None:
    exposed = scalar(
        system_connection,
        "SELECT (SELECT COUNT(*) FROM dba_tab_privs WHERE owner = 'UT3' AND grantee = 'PUBLIC')"
        " + (SELECT COUNT(*) FROM dba_synonyms WHERE owner = 'PUBLIC' AND table_owner = 'UT3') FROM dual",
    )
    assert exposed == 0
