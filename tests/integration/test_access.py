import os
import secrets
import time
from collections.abc import Callable
from pathlib import Path

import oracledb
import pytest

from srdwh.access.matrix import EXPECTED
from srdwh.cli import main
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


def test_context_not_settable(connect: Connect) -> None:
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


DIMENSION = "SELECT cpty_sk, cpty_name, lei FROM srdwh_owner.gld_dim_counterparty"


def masked(lei: object) -> object:
    return None if lei is None else "*" * 16 + str(lei)[-4:]


@pytest.mark.usefixtures("gold_loaded")
def test_names_redacted_for_analyst(connect: Connect, owner_connection: oracledb.Connection) -> None:
    clear = {sk: (name, lei) for sk, name, lei in rows(owner_connection, DIMENSION)}
    with connect("ANALYST_CORP") as connection:
        seen = rows(connection, DIMENSION)
    with connect("RISK_MANAGER") as connection:
        managed = rows(connection, DIMENSION)
    assert seen
    assert {name for _, name, _ in seen} == {" "}
    assert all(lei == masked(clear[sk][1]) for sk, _, lei in seen)
    assert {sk: (name, lei) for sk, name, lei in managed} == {sk: clear[sk] for sk, _, _ in managed}


TRAIL = """
    SELECT dbusername, fga_policy_name FROM unified_audit_trail
    WHERE client_identifier = :marker AND fga_policy_name IS NOT NULL ORDER BY fga_policy_name"""
PIPELINE_TRAIL = """
    SELECT count(*) FROM unified_audit_trail
    WHERE fga_policy_name IN ('FGA_FACT_EXPOSURE', 'FGA_DIM_COUNTERPARTY')
        AND dbusername IN ('SRDWH_OWNER', 'SRDWH_ETL')"""


def read_marked(connect: Connect, account: str, sql: str) -> str:
    marker = f"fga-{secrets.token_hex(8)}"
    with connect(account) as connection:
        connection.client_identifier = marker
        rows(connection, sql)
    return marker


def audited(connect: Connect, marker: str) -> list[tuple[object, ...]]:
    deadline = time.monotonic() + 30
    with connect("AUDITOR") as connection:
        found = rows(connection, TRAIL, marker=marker)
        while not found and time.monotonic() < deadline:
            time.sleep(1)
            found = rows(connection, TRAIL, marker=marker)
    return found


@pytest.mark.usefixtures("gold_loaded")
def test_fga_visible_to_auditor_30s(connect: Connect) -> None:
    marker = read_marked(connect, "ANALYST_CORP", "SELECT sum(drawn_amt) FROM srdwh_owner.gld_fact_exposure")
    assert audited(connect, marker) == [("ANALYST_CORP", "FGA_FACT_EXPOSURE")]


@pytest.mark.usefixtures("gold_loaded")
def test_fga_traces_filter_on_redacted(connect: Connect) -> None:
    sql = "SELECT count(*) FROM srdwh_owner.gld_dim_counterparty WHERE cpty_name LIKE 'A%'"
    marker = read_marked(connect, "ANALYST_CORP", sql)
    assert audited(connect, marker) == [("ANALYST_CORP", "FGA_DIM_COUNTERPARTY")]


@pytest.mark.usefixtures("gold_loaded")
def test_pipeline_leaves_no_fga(connect: Connect, owner_connection: oracledb.Connection) -> None:
    rows(owner_connection, "SELECT sum(drawn_amt) FROM srdwh_owner.gld_fact_exposure")
    rows(owner_connection, "SELECT max(cpty_name), max(lei) FROM srdwh_owner.gld_dim_counterparty")
    marker = read_marked(connect, "RISK_MANAGER", "SELECT max(lei) FROM srdwh_owner.gld_dim_counterparty")
    assert audited(connect, marker) == [("RISK_MANAGER", "FGA_DIM_COUNTERPARTY")]
    with connect("AUDITOR") as connection:
        assert rows(connection, PIPELINE_TRAIL) == [(0,)]


def test_sec_schema_no_login() -> None:
    with pytest.raises(oracledb.DatabaseError, match="ORA-01017"):
        oracledb.connect(user="srdwh_sec", password=os.environ["SRDWH_ETL_PASSWORD"], dsn=os.environ["SRDWH_DSN"])


def access_check(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["srdwh", "access-check"])
    with pytest.raises(SystemExit) as raised:
        main()
    return int(str(raised.value.code)), capsys.readouterr().out


@pytest.mark.usefixtures("gold_loaded")
def test_access_check_exit_0(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    code, out = access_check(capsys, monkeypatch)
    assert (code, "KO" in out) == (0, False), out
    assert [line.split()[0] for line in out.splitlines()[1:]] == [e.account for e in EXPECTED]


@pytest.mark.usefixtures("gold_loaded")
def test_access_check_detects_extra_grant(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, system_connection: oracledb.Connection
) -> None:
    with system_connection.cursor() as cursor:
        cursor.execute("GRANT SELECT ON srdwh_owner.ref_segment TO r_analyst")
    try:
        code, out = access_check(capsys, monkeypatch)
    finally:
        with system_connection.cursor() as cursor:
            cursor.execute("REVOKE SELECT ON srdwh_owner.ref_segment FROM r_analyst")
    assert code == 1
    assert "ANALYST_CORP hidden: expected denied, observed REF_SEGMENT" in out
