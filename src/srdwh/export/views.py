from datetime import date
from pathlib import Path
from types import MappingProxyType

import oracledb
import polars as pl

from srdwh.files import parquet, write_atomic

QUERIES = MappingProxyType(
    {
        "v_rwa_by_class": "SELECT * FROM srdwh_owner.v_rwa_by_class WHERE as_of_date = :as_of",
        "v_rwa_trend": "SELECT * FROM srdwh_owner.v_rwa_trend WHERE as_of_date = :as_of",
        "v_top_exposures": "SELECT * FROM srdwh_owner.v_top_exposures WHERE as_of_date = :as_of",
    }
)
PART = "part-0.parquet"


def export_path(exports: Path, view: str, as_of: date) -> Path:
    return exports / view / f"as_of_date={as_of.isoformat()}" / PART


def export_as_of(connection: oracledb.Connection, as_of: date, exports: Path) -> int:
    return sum(_export(connection, view, as_of, exports) for view in QUERIES)


def _export(connection: oracledb.Connection, view: str, as_of: date, exports: Path) -> int:
    fetched = connection.fetch_df_all(QUERIES[view], {"as_of": as_of}, fetch_decimals=True)
    frame = pl.DataFrame(fetched).rename(str.lower).with_columns(pl.col(pl.Datetime).cast(pl.Date))
    write_atomic(export_path(exports, view, as_of), parquet(frame))
    return frame.height
