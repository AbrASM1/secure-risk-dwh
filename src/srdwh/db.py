import time
from collections.abc import Callable

import oracledb

from srdwh.config import Credentials

RETRY_FOR_SECONDS = 60.0
RETRY_PAUSE_SECONDS = 2.0
MODULE = "srdwh"
Opener = Callable[..., oracledb.Connection]


def connect(
    credentials: Credentials,
    run_id: int | None,
    step: str,
    *,
    retry_for: float = RETRY_FOR_SECONDS,
    opener: Opener = oracledb.connect,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> oracledb.Connection:
    connection = _open(credentials, retry_for, opener, sleep, clock)
    tag(connection, run_id, step)
    return connection


def tag(connection: oracledb.Connection, run_id: int | None, step: str) -> None:
    connection.client_identifier = "" if run_id is None else str(run_id)
    connection.module = MODULE
    connection.action = step


def _open(
    credentials: Credentials,
    retry_for: float,
    opener: Opener,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> oracledb.Connection:
    deadline = clock() + retry_for
    while True:
        try:
            return opener(user=credentials.user, password=credentials.password, dsn=credentials.dsn)
        except oracledb.OperationalError:
            remaining = deadline - clock()
            if remaining <= 0:
                raise
            sleep(min(RETRY_PAUSE_SECONDS, remaining))
