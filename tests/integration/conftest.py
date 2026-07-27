import os
from collections.abc import Iterator

import oracledb
import pytest

from srdwh.config import credentials
from tests.integration.db import Connect


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
