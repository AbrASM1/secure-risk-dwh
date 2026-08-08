import oracledb
import pytest

from tests.integration.db import Connect, rows

pytestmark = pytest.mark.db


@pytest.mark.parametrize(
    ("statement", "error"),
    [
        ("UPDATE srdwh_owner.brz_counterparty SET cpty_id = cpty_id WHERE 1 = 0", "ORA-41900: missing UPDATE"),
        ("DELETE FROM srdwh_owner.brz_exposure WHERE 1 = 0", "ORA-41900: missing DELETE"),
        (
            "MERGE INTO srdwh_owner.brz_counterparty t USING (SELECT 'x' AS cpty_id FROM dual) s "
            "ON (t.cpty_id = s.cpty_id) WHEN MATCHED THEN UPDATE SET t.lei = t.lei "
            "WHEN NOT MATCHED THEN INSERT (cpty_id) VALUES (s.cpty_id)",
            "ORA-41900: missing UPDATE",
        ),
        ("TRUNCATE TABLE srdwh_owner.brz_exposure", "ORA-01031"),
        ("ALTER TABLE srdwh_owner.brz_counterparty TRUNCATE PARTITION p_first", "ORA-41900: missing ALTER"),
    ],
)
def test_etl_dml_on_bronze_refused(connect: Connect, statement: str, error: str) -> None:
    with connect("SRDWH_ETL") as connection, connection.cursor() as cursor:
        with pytest.raises(oracledb.DatabaseError, match=error):
            cursor.execute(statement)
        connection.rollback()


def test_etl_bronze_privileges_are_insert_and_select(system_connection: oracledb.Connection) -> None:
    granted = rows(
        system_connection,
        "SELECT table_name, privilege FROM dba_tab_privs "
        "WHERE grantee = 'SRDWH_ETL' AND owner = 'SRDWH_OWNER' AND table_name LIKE 'BRZ%' ORDER BY 1, 2",
    )
    assert granted == [
        ("BRZ_COUNTERPARTY", "INSERT"),
        ("BRZ_COUNTERPARTY", "SELECT"),
        ("BRZ_EXPOSURE", "INSERT"),
        ("BRZ_EXPOSURE", "SELECT"),
    ]
