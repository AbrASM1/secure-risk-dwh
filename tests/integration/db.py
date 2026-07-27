from collections.abc import Callable

import oracledb

Connect = Callable[[str], oracledb.Connection]


def rows(connection: oracledb.Connection, sql: str, **binds: object) -> list[tuple[object, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(sql, binds)
        result: list[tuple[object, ...]] = cursor.fetchall()
    return result


def execute(connection: oracledb.Connection, sql: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql)
