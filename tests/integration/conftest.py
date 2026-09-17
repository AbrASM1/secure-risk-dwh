import os
from collections.abc import Callable, Iterator

import oracledb
import pytest

from srdwh.config import Profile, credentials
from tests.integration.db import Connect
from tests.integration.pipeline import retire, unique_profile


@pytest.fixture(scope="session")
def system_connection() -> Iterator[oracledb.Connection]:
    connection = oracledb.connect(user="system", password=os.environ["ORACLE_PASSWORD"], dsn=os.environ["SRDWH_DSN"])
    yield connection
    connection.close()


@pytest.fixture(scope="session")
def connect() -> Connect:
    def open_as(account: str) -> oracledb.Connection:
        found = credentials(account)
        return oracledb.connect(user=found.user, password=found.password, dsn=found.dsn)

    return open_as


@pytest.fixture(scope="session")
def owner_connection(connect: Connect) -> Iterator[oracledb.Connection]:
    connection = connect("SRDWH_OWNER")
    yield connection
    connection.close()


@pytest.fixture
def pipeline_profile(owner_connection: oracledb.Connection) -> Iterator[Callable[[int], Profile]]:
    allocated: list[Profile] = []

    def allocate(as_of_count: int = 1) -> Profile:
        allocated.append(unique_profile(as_of_count))
        return allocated[-1]

    yield allocate
    for profile in allocated:
        retire(owner_connection, profile)
