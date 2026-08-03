from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

import oracledb
import polars as pl

from srdwh.ingest.landing import Delivery
from srdwh.ingest.registry import call, function, load_state

OWNER = "SRDWH_OWNER"
BRONZE_TABLES = MappingProxyType({"counterparty": "BRZ_COUNTERPARTY", "exposure": "BRZ_EXPOSURE"})


@dataclass(frozen=True)
class LoadResult:
    load_id: int
    status: str
    rows_loaded: int | None


def load(connection: oracledb.Connection, run_id: int, delivery: Delivery, batch_size: int) -> LoadResult:
    partition = delivery.partition
    load_id = function(
        connection,
        "register_load",
        run_id,
        partition.feed,
        partition.as_of,
        partition.file_path,
        delivery.sha256,
        delivery.frame.height,
    )
    connection.commit()
    rows = bronze_rows(delivery, load_id, datetime.now(UTC))
    try:
        connection.direct_path_load(OWNER, BRONZE_TABLES[partition.feed], rows.columns, rows, batch_size=batch_size)
    except oracledb.Error as error:
        call(connection, "fail_load", run_id, load_id, str(error).splitlines()[0])
        connection.commit()
        raise
    call(connection, "close_load", run_id, load_id)
    connection.commit()
    return LoadResult(load_id, *load_state(connection, load_id))


def bronze_rows(delivery: Delivery, load_id: int, ingested_at: datetime) -> pl.DataFrame:
    return delivery.frame.with_columns(
        pl.lit(load_id, pl.Int64).alias("load_id"),
        pl.lit(delivery.partition.file_path).alias("src_file"),
        pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("src_row"),
        pl.lit(ingested_at, pl.Datetime("us", "UTC")).alias("ingested_at"),
    )
