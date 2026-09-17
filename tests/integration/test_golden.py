from datetime import date
from decimal import Decimal

import oracledb
import polars as pl
import pytest

pytestmark = pytest.mark.db
GOLDEN_AS_OF = date(2000, 1, 31)
COMPARED = """
    SELECT g.golden_id, g.rwa AS expected_rwa, g.e_star AS expected_e_star, r.rwa, r.e_star
    FROM srdwh_owner.ut_golden_rwa g
    LEFT JOIN srdwh_owner.gld_fact_rwa r ON r.as_of_date = g.as_of_date AND r.exposure_id = g.golden_id
    ORDER BY g.golden_id"""


def test_golden_set_exact_in_python(owner_connection: oracledb.Connection) -> None:
    try:
        with owner_connection.cursor() as cursor:
            cursor.callproc("srdwh_owner.ut_data.load_golden")
            cursor.callproc("srdwh_owner.ut_data.build", [GOLDEN_AS_OF])
        frame = pl.DataFrame(owner_connection.fetch_df_all(COMPARED, fetch_decimals=True))
    finally:
        owner_connection.rollback()
    assert frame.height == 10
    assert frame.schema["RWA"] == pl.Decimal(20, 2)
    assert frame["RWA"].to_list() == frame["EXPECTED_RWA"].to_list()
    assert frame["E_STAR"].to_list() == frame["EXPECTED_E_STAR"].to_list()
    assert sum(frame["RWA"].to_list(), Decimal(0)) == Decimal("2211000.00")
