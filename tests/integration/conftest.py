import os
from collections.abc import Iterator

import oracledb
import pytest


@pytest.fixture(scope="session")
def system_connection() -> Iterator[oracledb.Connection]:
    connection = oracledb.connect(user="system", password=os.environ["ORACLE_PASSWORD"], dsn=os.environ["SRDWH_DSN"])
    yield connection
    connection.close()
