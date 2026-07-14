import pandera.polars as pa
import polars as pl
from pandera.api.polars.types import PolarsData
from pandera.errors import SchemaErrors


class ContractError(ValueError):
    pass


def max_bytes(limit: int) -> pa.Check:
    def within(data: PolarsData) -> pl.LazyFrame:
        return data.lazyframe.select(pl.col(data.key).str.len_bytes() <= limit)

    return pa.Check(within, name="max_bytes")


def validate(schema: pa.DataFrameSchema, frame: pl.DataFrame, source: str) -> pl.DataFrame:
    try:
        return schema.validate(frame, lazy=True)
    except SchemaErrors as errors:
        summary = _summary(errors.failure_cases)
    raise ContractError(f"{source}: {summary}") from None


def _summary(failures: pl.DataFrame) -> str:
    return str(
        failures.lazy()
        .group_by("column", "check", maintain_order=True)
        .agg(pl.len().alias("rows"), (pl.col("index").min() + 1).alias("first_src_row"))
        .select(
            pl.format(
                "column={} check={} rows={} first_src_row={}",
                pl.col("column").fill_null("-"),
                pl.col("check"),
                pl.col("rows"),
                pl.col("first_src_row").cast(pl.Utf8).fill_null("-"),
            ).str.join("; ")
        )
        .collect()
        .item()
    )
