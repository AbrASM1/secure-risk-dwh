from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import oracledb
import pytest

from srdwh.config import Credentials
from srdwh.db import RETRY_FOR_SECONDS, connect

MARKER = "Zq7MarkerValue42abcdefgh"
CREDENTIALS = Credentials(user="SRDWH_ETL", dsn="localhost:1521/FREEPDB1", password=MARKER)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.pauses: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.pauses.append(seconds)
        self.now += seconds


def opener(failures: int, error: Exception) -> Callable[..., oracledb.Connection]:
    attempts = iter(range(failures + 1))

    def open_connection(**_: str) -> oracledb.Connection:
        if next(attempts, failures) < failures:
            raise error
        return cast(oracledb.Connection, SimpleNamespace())

    return open_connection


def test_retry_bounded_60s() -> None:
    clock = Clock()
    with pytest.raises(oracledb.OperationalError):
        connect(
            CREDENTIALS,
            1,
            "lock",
            opener=opener(10_000, oracledb.OperationalError("down")),
            sleep=clock.sleep,
            clock=clock.time,
        )
    assert sum(clock.pauses) == pytest.approx(RETRY_FOR_SECONDS)
    assert max(clock.pauses) <= 2.0


def test_retry_then_tagged_connection() -> None:
    clock = Clock()
    connection = connect(
        CREDENTIALS,
        42,
        "ingest",
        opener=opener(2, oracledb.OperationalError("down")),
        sleep=clock.sleep,
        clock=clock.time,
    )
    assert clock.pauses == [2.0, 2.0]
    assert (connection.client_identifier, connection.module, connection.action) == ("42", "srdwh", "ingest")


def test_authentication_error_not_retried() -> None:
    clock = Clock()
    with pytest.raises(oracledb.DatabaseError):
        connect(
            CREDENTIALS,
            None,
            "config",
            opener=opener(1, oracledb.DatabaseError("ORA-01017")),
            sleep=clock.sleep,
            clock=clock.time,
        )
    assert clock.pauses == []
