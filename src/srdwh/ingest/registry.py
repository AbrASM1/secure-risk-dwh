from datetime import date

import oracledb

PACKAGE = "srdwh_owner.pkg_ops"


def call(connection: oracledb.Connection, procedure: str, *arguments: object) -> None:
    with connection.cursor() as cursor:
        cursor.callproc(f"{PACKAGE}.{procedure}", list(arguments))


def function(connection: oracledb.Connection, name: str, *arguments: object) -> int:
    with connection.cursor() as cursor:
        return int(cursor.callfunc(f"{PACKAGE}.{name}", int, list(arguments)))


def is_loaded(connection: oracledb.Connection, feed: str, as_of: date, sha256: str) -> bool:
    return function(connection, "is_loaded", feed, as_of, sha256) == 1


def load_state(connection: oracledb.Connection, load_id: int) -> tuple[str, int | None]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, rows_loaded FROM srdwh_owner.ops_load_registry WHERE load_id = :load_id", load_id=load_id
        )
        status, rows_loaded = cursor.fetchone()
    return str(status), None if rows_loaded is None else int(rows_loaded)
