import polars as pl
import pytest

from srdwh.contracts.feeds import (
    BRONZE_MAX_BYTES,
    CONTRACT_VERSION,
    COUNTERPARTY_COLUMNS,
    EXPOSURE_COLUMNS,
    FIELD_LENGTHS,
    validate_feed,
)
from srdwh.contracts.validation import ContractError

NAME = "Hélène Secretname"
LEI = "529900T8BM49AURSDO55"


def counterparty(rows: int = 3) -> pl.DataFrame:
    values = {column: [f"{column}{i}" for i in range(rows)] for column in COUNTERPARTY_COLUMNS}
    data = values | {"cpty_name": [NAME] * rows, "lei": ([LEI] + [""] * rows)[:rows]}
    return pl.DataFrame(data, schema=dict.fromkeys(COUNTERPARTY_COLUMNS, pl.Utf8))


def test_columns_match_spec() -> None:
    assert COUNTERPARTY_COLUMNS == (
        "cpty_id",
        "cpty_name",
        "lei",
        "segment_code",
        "country",
        "rating",
        "default_flag",
        "as_of_date",
    )
    assert EXPOSURE_COLUMNS == (
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


def test_field_lengths_match_model() -> None:
    assert dict(FIELD_LENGTHS) == {"cpty_id": 20, "exposure_id": 30, "cpty_name": 200, "lei": 20}
    assert CONTRACT_VERSION


def test_valid_feed_passes() -> None:
    frame = counterparty()
    assert validate_feed("counterparty", frame).equals(frame)
    assert validate_feed("counterparty", counterparty(0)).height == 0
    exposure = pl.DataFrame({column: ["", "1"] for column in EXPOSURE_COLUMNS})
    assert validate_feed("exposure", exposure).equals(exposure)


def test_value_at_bronze_limit_passes() -> None:
    frame = counterparty().with_columns(pl.lit("é" * (BRONZE_MAX_BYTES // 2)).alias("cpty_name"))
    assert validate_feed("counterparty", frame).equals(frame)


@pytest.mark.parametrize(
    ("change", "check"),
    [
        (lambda f: f.drop("lei"), "column_in_dataframe"),
        (lambda f: f.with_columns(pl.lit("x").alias("extra")), "column_in_schema"),
        (lambda f: f.select(reversed(f.columns)), "column_ordered"),
        (lambda f: f.with_columns(pl.lit(1).alias("rating")), "dtype"),
        (lambda f: f.with_columns(pl.lit(None, pl.Utf8).alias("country")), "not_nullable"),
        (lambda f: f.with_columns(pl.lit("é" * 2001).alias("cpty_name")), "max_bytes"),
    ],
)
def test_structural_violation_fails(change: object, check: str) -> None:
    assert callable(change)
    with pytest.raises(ContractError, match=check):
        validate_feed("counterparty", change(counterparty()))


def test_errors_never_quote_values() -> None:
    frame = counterparty().with_columns(
        pl.when(pl.int_range(pl.len()) == 1).then(pl.lit(NAME * 300)).otherwise(pl.col("cpty_name")).alias("cpty_name"),
        pl.when(pl.int_range(pl.len()) == 2).then(pl.lit(LEI * 300)).otherwise(pl.col("lei")).alias("lei"),
    )
    with pytest.raises(ContractError) as error:
        validate_feed("counterparty", frame)
    message = str(error.value)
    assert NAME not in message
    assert LEI not in message
    assert "column=cpty_name check=max_bytes rows=1 first_src_row=2" in message
    assert "column=lei check=max_bytes rows=1 first_src_row=3" in message
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__


def test_unknown_feed_fails() -> None:
    with pytest.raises(ContractError, match="unknown feed"):
        validate_feed("trade", counterparty())
