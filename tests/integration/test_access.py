import oracledb
import pytest

from tests.integration.db import Connect, rows

pytestmark = pytest.mark.db
CONTEXT = "SELECT sys_context('SRDWH_CTX', 'PROFILE'), sys_context('SRDWH_CTX', 'SEGMENT') FROM dual"
ROLES = "SELECT role FROM session_roles WHERE role LIKE 'R\\_%' ESCAPE '\\' OR role = 'AUDIT_VIEWER' ORDER BY role"
PROFILES = {
    "ANALYST_CORP": (("ANALYST", "CORPORATE"), ["R_ANALYST"]),
    "ANALYST_RETAIL": (("ANALYST", "RETAIL"), ["R_ANALYST"]),
    "RISK_MANAGER": (("RISK_MANAGER", None), ["R_RISK_MANAGER"]),
    "AUDITOR": (("AUDITOR", None), ["AUDIT_VIEWER", "R_AUDITOR"]),
    "PROBE_NOPROFILE": ((None, None), ["R_ANALYST"]),
    "SRDWH_ETL": ((None, None), []),
}


@pytest.mark.parametrize("account", PROFILES)
def test_logon_sets_profile_context(connect: Connect, account: str) -> None:
    context, roles = PROFILES[account]
    with connect(account) as connection:
        assert rows(connection, CONTEXT) == [context]
        assert [role for (role,) in rows(connection, ROLES)] == roles


def test_context_set_only_by_its_package(connect: Connect) -> None:
    with connect("ANALYST_CORP") as connection, connection.cursor() as cursor:
        with pytest.raises(oracledb.DatabaseError, match="ORA-01031"):
            cursor.callproc("dbms_session.set_context", ["SRDWH_CTX", "SEGMENT", "RETAIL"])
        assert rows(connection, CONTEXT) == [("ANALYST", "CORPORATE")]
