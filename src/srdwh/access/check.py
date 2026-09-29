import secrets
import time
from collections.abc import Callable
from types import MappingProxyType
from typing import TextIO

import oracledb

from srdwh.access.matrix import DENIED, EXPECTED, NONE, RECORDS, Cell, Expected, Observed, cells, names_state, render
from srdwh.config import credentials
from srdwh.db import connect

EXIT_OK = 0
EXIT_FAILURE = 1
TABLE_MISSING = 942
AUDIT_WAIT_SECONDS = 30.0
REFERENCE = "SELECT DISTINCT segment_code FROM srdwh_owner.v_rwa_trend"
DETAIL = "SELECT DISTINCT segment_code FROM srdwh_owner.gld_fact_rwa"
MARTS = "SELECT DISTINCT segment_code FROM srdwh_owner.gld_mart_rwa"
NAMES = (
    "SELECT count(*), count(CASE WHEN cpty_name = ' ' AND (lei IS NULL OR lei LIKE '****************%') THEN 1 END) "
    "FROM srdwh_owner.gld_dim_counterparty"
)
ROLES = "SELECT role FROM session_roles"
PRIVS = "SELECT privilege FROM session_privs"
AUDIT = "SELECT count(*) FROM unified_audit_trail WHERE client_identifier = :marker AND fga_policy_name IS NOT NULL"
HIDDEN = MappingProxyType(
    {
        "BRZ_COUNTERPARTY": "SELECT 1 FROM srdwh_owner.brz_counterparty WHERE 1 = 0",
        "SLV_COUNTERPARTY": "SELECT 1 FROM srdwh_owner.slv_counterparty WHERE 1 = 0",
        "OPS_RUN_LOG": "SELECT 1 FROM srdwh_owner.ops_run_log WHERE 1 = 0",
        "REF_SEGMENT": "SELECT 1 FROM srdwh_owner.ref_segment WHERE 1 = 0",
        "PARAM_CCF": "SELECT 1 FROM srdwh_owner.param_ccf WHERE 1 = 0",
        "SEC_USER_ACCESS": "SELECT 1 FROM srdwh_sec.sec_user_access WHERE 1 = 0",
    }
)


def access_check(stream: TextIO) -> int:
    marker = f"access-check-{secrets.token_hex(8)}"
    with connect(credentials("SRDWH_ETL"), None, "access-check") as connection:
        segments = frozenset(str(value) for (value,) in _fetch(connection, REFERENCE) or [])
    matrix = tuple(cell for expected in EXPECTED for cell in _check(expected, marker, segments))
    print(render(matrix), file=stream)
    return EXIT_OK if segments and all(cell.ok for cell in matrix) else EXIT_FAILURE


def _check(expected: Expected, marker: str, segments: frozenset[str]) -> tuple[Cell, ...]:
    with connect(credentials(expected.account), None, "access-check") as connection:
        connection.client_identifier = marker
        return cells(expected, _observe(connection, expected.account, marker), segments)


def _observe(connection: oracledb.Connection, account: str, marker: str) -> Observed:
    names = _fetch(connection, NAMES)
    return Observed(
        account=account,
        roles=_values(connection, ROLES),
        privs=_values(connection, PRIVS),
        detail=_optional_values(connection, DETAIL),
        names=DENIED if names is None else names_state(int(str(names[0][0])), int(str(names[0][1]))),
        marts=_optional_values(connection, MARTS),
        hidden=frozenset(name for name, sql in HIDDEN.items() if _fetch(connection, sql) is not None),
        audit=_audit(connection, marker),
    )


def _audit(
    connection: oracledb.Connection,
    marker: str,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    deadline = clock() + AUDIT_WAIT_SECONDS
    found = _fetch(connection, AUDIT, marker=marker)
    while found is not None and found[0][0] == 0 and clock() < deadline:
        sleep(1.0)
        found = _fetch(connection, AUDIT, marker=marker)
    if found is None:
        return DENIED
    return RECORDS if found[0][0] else NONE


def _values(connection: oracledb.Connection, sql: str) -> frozenset[str]:
    return frozenset(str(value) for (value,) in _fetch(connection, sql) or [])


def _optional_values(connection: oracledb.Connection, sql: str) -> frozenset[str] | None:
    found = _fetch(connection, sql)
    return None if found is None else frozenset(str(value) for (value,) in found)


def _fetch(connection: oracledb.Connection, sql: str, **binds: object) -> list[tuple[object, ...]] | None:
    try:
        with connection.cursor() as cursor:
            return list(cursor.execute(sql, binds))
    except oracledb.DatabaseError as error:
        if error.args[0].code == TABLE_MISSING:
            return None
        raise
