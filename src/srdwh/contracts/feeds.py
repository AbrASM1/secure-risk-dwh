from types import MappingProxyType

import pandera.polars as pa
import polars as pl

from srdwh.contracts.validation import ContractError, max_bytes, validate

CONTRACT_VERSION = "1"
BRONZE_MAX_BYTES = 4000
COUNTERPARTY_COLUMNS = (
    "cpty_id",
    "cpty_name",
    "lei",
    "segment_code",
    "country",
    "rating",
    "default_flag",
    "as_of_date",
)
EXPOSURE_COLUMNS = (
    "exposure_id",
    "cpty_id",
    "product_code",
    "drawn_amt",
    "undrawn_amt",
    "collateral_amt",
    "collateral_type",
    "currency",
    "as_of_date",
)
FIELD_LENGTHS = MappingProxyType({"cpty_id": 20, "exposure_id": 30, "cpty_name": 200, "lei": 20})


def _schema(feed: str, columns: tuple[str, ...]) -> pa.DataFrameSchema:
    return pa.DataFrameSchema(
        {name: pa.Column(pl.Utf8, nullable=False, checks=max_bytes(BRONZE_MAX_BYTES)) for name in columns},
        strict=True,
        ordered=True,
        name=feed,
    )


FEEDS = MappingProxyType(
    {
        "counterparty": _schema("counterparty", COUNTERPARTY_COLUMNS),
        "exposure": _schema("exposure", EXPOSURE_COLUMNS),
    }
)


def validate_feed(feed: str, frame: pl.DataFrame) -> pl.DataFrame:
    if feed not in FEEDS:
        raise ContractError(f"unknown feed {feed!r}")
    return validate(FEEDS[feed], frame, feed)
