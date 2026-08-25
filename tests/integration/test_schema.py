from pathlib import Path

import oracledb
import pytest

from srdwh.contracts.feeds import COUNTERPARTY_COLUMNS, EXPOSURE_COLUMNS
from srdwh.contracts.reference import read_reference
from tests.integration.db import rows

pytestmark = pytest.mark.db
REF = Path(__file__).resolve().parents[2] / "db" / "ref"
TECHNICAL = [
    ("LOAD_ID", "NUMBER", 22),
    ("SRC_FILE", "VARCHAR2", 1000),
    ("SRC_ROW", "NUMBER", 22),
    ("INGESTED_AT", "TIMESTAMP(6) WITH TIME ZONE", 13),
]
REFERENCES = {
    "segment": "SELECT segment_code, lei_required, label FROM srdwh_owner.ref_segment",
    "rating": "SELECT rating_code, rating_bucket, rating_rank FROM srdwh_owner.ref_rating",
    "product": "SELECT product_code, product_type, label FROM srdwh_owner.ref_product",
    "collateral_type": "SELECT collateral_type, label FROM srdwh_owner.ref_collateral_type",
    "country": "SELECT country_code, label FROM srdwh_owner.ref_country",
    "reason_code": "SELECT reason_code, feed, rule_text FROM srdwh_owner.ref_reason_code",
}
EMPTY_CATALOGS = (
    "SELECT COUNT(*) FROM dba_constraints WHERE owner = 'SRDWH_OWNER' AND table_name = :name",
    "SELECT COUNT(*) FROM dba_indexes WHERE table_owner = 'SRDWH_OWNER' AND table_name = :name",
    "SELECT COUNT(*) FROM dba_triggers WHERE table_owner = 'SRDWH_OWNER' AND table_name = :name",
)


def columns(connection: oracledb.Connection, table: str) -> list[tuple[object, ...]]:
    return rows(
        connection,
        "SELECT column_name, data_type, data_length FROM dba_tab_columns "
        "WHERE owner = 'SRDWH_OWNER' AND table_name = :name ORDER BY column_id",
        name=table,
    )


@pytest.mark.parametrize(("reference", "query"), sorted(REFERENCES.items()))
def test_reference_table_matches_csv(system_connection: oracledb.Connection, reference: str, query: str) -> None:
    loaded = sorted(tuple(str(value) for value in row) for row in rows(system_connection, query))
    assert loaded == sorted(read_reference(REF, reference).rows())


@pytest.mark.parametrize(
    ("table", "feed_columns"), [("BRZ_COUNTERPARTY", COUNTERPARTY_COLUMNS), ("BRZ_EXPOSURE", EXPOSURE_COLUMNS)]
)
def test_bronze_follows_contract(
    system_connection: oracledb.Connection, table: str, feed_columns: tuple[str, ...]
) -> None:
    feed = [(name.upper(), "VARCHAR2", 4000) for name in feed_columns]
    assert columns(system_connection, table) == feed + TECHNICAL
    partitioning = rows(
        system_connection,
        "SELECT p.partitioning_type, p.interval, k.column_name FROM dba_part_tables p "
        "JOIN dba_part_key_columns k ON k.owner = p.owner AND k.name = p.table_name "
        "WHERE p.owner = 'SRDWH_OWNER' AND p.table_name = :name",
        name=table,
    )
    assert partitioning == [("RANGE", "1", "LOAD_ID")]
    for query in EMPTY_CATALOGS:
        assert rows(system_connection, query, name=table) == [(0,)], query


def test_ops_identity_and_sequence(system_connection: oracledb.Connection) -> None:
    identity = rows(
        system_connection,
        "SELECT table_name, column_name, generation_type FROM dba_tab_identity_cols "
        "WHERE owner = 'SRDWH_OWNER' AND table_name LIKE 'OPS%' ORDER BY table_name",
    )
    assert identity == [
        ("OPS_ERR_LOG", "ERR_ID", "ALWAYS"),
        ("OPS_LOAD_REGISTRY", "LOAD_ID", "ALWAYS"),
        ("OPS_RUN_LOG", "LOG_ID", "ALWAYS"),
    ]
    assert rows(
        system_connection,
        "SELECT sequence_name FROM dba_sequences WHERE sequence_owner = 'SRDWH_OWNER' "
        "AND sequence_name NOT LIKE 'ISEQ$$%'",
    ) == [("OPS_RUN_SEQ",)]


def test_reference_loading_leaves_nothing_behind(system_connection: oracledb.Connection) -> None:
    assert (
        rows(system_connection, "SELECT directory_name FROM dba_directories WHERE directory_name LIKE 'SRDWH%'") == []
    )
    assert rows(system_connection, "SELECT table_name FROM dba_external_tables WHERE owner = 'SRDWH_OWNER'") == []


def test_interval_partition_creation_keeps_the_transaction_open(system_connection: oracledb.Connection) -> None:
    partitions = (
        "SELECT count(*) FROM dba_tab_partitions WHERE table_owner = 'SRDWH_OWNER' AND table_name = 'SLV_COUNTERPARTY'"
    )
    before = int(str(rows(system_connection, partitions)[0][0]))
    with system_connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO srdwh_owner.slv_counterparty (as_of_date, cpty_id, cpty_name, segment_code, country, "
            "rating, default_flag, load_id, src_row) "
            "VALUES (DATE '2002-06-30', 'UW05', 'Probe SA', 'SME', 'FR', 'NR', 'N', 0, 1)"
        )
    created = int(str(rows(system_connection, partitions)[0][0]))
    system_connection.rollback()
    remaining = rows(system_connection, "SELECT count(*) FROM srdwh_owner.slv_counterparty WHERE cpty_id = 'UW05'")
    assert created >= before
    assert remaining == [(0,)]
