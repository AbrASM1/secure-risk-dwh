from collections.abc import Callable
from pathlib import Path

import oracledb
import pytest

from srdwh.config import Profile
from tests.integration.db import Connect, rows
from tests.integration.pipeline import landing, run

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


PROTECTED = ("gld_fact_exposure", "gld_fact_rwa", "gld_dim_counterparty", "gld_mart_rwa")


def segments(connection: oracledb.Connection, table: str) -> set[object]:
    return {segment for (segment,) in rows(connection, f"SELECT DISTINCT segment_code FROM srdwh_owner.{table}")}


@pytest.fixture
def gold_loaded(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    pipeline_profile: Callable[[int], Profile],
) -> Profile:
    profile = pipeline_profile(1)
    assert run(landing(tmp_path, profile), capsys, monkeypatch)[0] == 0
    return profile


@pytest.mark.usefixtures("gold_loaded")
def test_probe_sees_no_row(connect: Connect) -> None:
    with connect("PROBE_NOPROFILE") as connection:
        assert [rows(connection, f"SELECT count(*) FROM srdwh_owner.{table}")[0][0] for table in PROTECTED] == [0] * 4


@pytest.mark.usefixtures("gold_loaded")
@pytest.mark.parametrize(("account", "segment"), [("ANALYST_CORP", "CORPORATE"), ("ANALYST_RETAIL", "RETAIL")])
def test_analyst_sees_own_segment(connect: Connect, account: str, segment: str) -> None:
    with connect(account) as connection:
        assert [segments(connection, table) for table in PROTECTED] == [{segment}] * 4


@pytest.mark.usefixtures("gold_loaded")
def test_risk_manager_sees_every_segment(connect: Connect) -> None:
    with connect("RISK_MANAGER") as connection:
        assert all(len(segments(connection, table)) == 5 for table in PROTECTED)
