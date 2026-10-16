import time
import warnings
from collections.abc import Callable

import oracledb

Connect = Callable[[str], oracledb.Connection]
REDACTION_ERROR = "ORA-28075"
REDACTION_WINDOW_S = 30.0


def rows(connection: oracledb.Connection, sql: str, **binds: object) -> list[tuple[object, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(sql, binds)
        result: list[tuple[object, ...]] = cursor.fetchall()
    return result


def execute(connection: oracledb.Connection, sql: str, **binds: object) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql, binds)


def read_redacted(connect: Connect, account: str, sql: str, **binds: object) -> list[tuple[object, ...]]:
    deadline = time.monotonic() + REDACTION_WINDOW_S
    while True:
        with connect(account) as connection:
            try:
                return rows(connection, sql, **binds)
            except oracledb.DatabaseError as error:
                if REDACTION_ERROR not in str(error) or time.monotonic() > deadline:
                    raise
                warnings.warn(f"{REDACTION_ERROR} on a redacted read, reconnecting", stacklevel=2)
        time.sleep(1)
