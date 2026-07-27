import os

import oracledb
import pytest

from tests.integration.db import Connect, rows

pytestmark = pytest.mark.db
APPLICATION = ("SRDWH_OWNER", "SRDWH_SEC", "SRDWH_ETL")
PROFILES = ("ANALYST_CORP", "ANALYST_RETAIL", "RISK_MANAGER", "AUDITOR", "PROBE_NOPROFILE")
LOGINS = ("SRDWH_OWNER", "SRDWH_ETL", *PROFILES)


def accounts() -> tuple[str, ...]:
    return APPLICATION + (PROFILES if os.environ["SRDWH_ENV"] in ("dev", "ci") else ())


def test_accounts_and_authentication(system_connection: oracledb.Connection) -> None:
    users = rows(system_connection, "SELECT username, authentication_type FROM dba_users WHERE oracle_maintained = 'N'")
    found = {str(name): str(kind) for name, kind in users}
    assert {name: found.get(name) for name in accounts()} == dict.fromkeys(accounts(), "PASSWORD") | {
        "SRDWH_SEC": "NONE"
    }


def test_owner_privileges_and_quotas(system_connection: oracledb.Connection) -> None:
    owner = {"grantee": "SRDWH_OWNER"}
    assert rows(system_connection, "SELECT privilege FROM dba_sys_privs WHERE grantee = :grantee", **owner) == [
        ("CREATE SESSION",)
    ]
    assert rows(
        system_connection,
        "SELECT owner, table_name, privilege FROM dba_tab_privs WHERE grantee = :grantee AND owner = 'SYS'",
        **owner,
    ) == [("SYS", "DBMS_LOCK", "EXECUTE")]
    quotas = rows(system_connection, "SELECT username, tablespace_name, max_bytes FROM dba_ts_quotas ORDER BY username")
    assert {(u, t, m) for u, t, m in quotas if u in APPLICATION} == {
        ("SRDWH_OWNER", "USERS", -1),
        ("SRDWH_SEC", "USERS", -1),
    }


def test_no_forbidden_privilege(system_connection: oracledb.Connection) -> None:
    ours = set(accounts())
    system = rows(system_connection, "SELECT grantee, privilege FROM dba_sys_privs")
    assert {privilege for grantee, privilege in system if grantee in ours} == {"CREATE SESSION"}
    assert [
        grant
        for grant in rows(system_connection, "SELECT grantee, granted_role FROM dba_role_privs")
        if grant[0] in ours
    ] == []
    executable = rows(
        system_connection,
        "SELECT grantee FROM dba_tab_privs "
        "WHERE owner = 'SYS' AND table_name IN ('DBMS_RLS', 'DBMS_REDACT', 'DBMS_FGA')",
    )
    assert [grant for grant in executable if grant[0] in ours] == []


@pytest.mark.parametrize("account", LOGINS)
def test_login_with_environment_password(connect: Connect, account: str) -> None:
    if account in PROFILES and os.environ["SRDWH_ENV"] not in ("dev", "ci"):
        pytest.skip("profile accounts exist in dev and ci only")
    with connect(account) as connection:
        assert rows(connection, "SELECT USER FROM dual") == [(account,)]


def test_schema_only_account_cannot_log_in() -> None:
    with pytest.raises(oracledb.DatabaseError, match="ORA-01017"):
        oracledb.connect(user="srdwh_sec", password=os.environ["SRDWH_ETL_PASSWORD"], dsn=os.environ["SRDWH_DSN"])


def test_owner_reaches_utplsql_through_private_synonyms(
    connect: Connect, system_connection: oracledb.Connection
) -> None:
    with connect("SRDWH_OWNER") as connection:
        assert str(rows(connection, "SELECT ut.version() FROM dual")[0][0]).startswith("v.3.2.3.")
    assert rows(
        system_connection, "SELECT COUNT(*) FROM dba_synonyms WHERE owner = 'SRDWH_OWNER' AND table_owner = 'UT3'"
    )[0][0]
