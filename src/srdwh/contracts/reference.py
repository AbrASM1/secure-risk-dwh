from pathlib import Path
from types import MappingProxyType

import pandera.polars as pa
import polars as pl
from pandera.api.polars.types import PolarsData

from srdwh.contracts.validation import ContractError, max_bytes, validate

CODE = r"^[A-Z][A-Z_]{0,19}$"


def _text(limit: int, *checks: pa.Check, unique: bool = False) -> pa.Column:
    return pa.Column(pl.Utf8, nullable=False, unique=unique, checks=[max_bytes(limit), *checks])


def _code(unique: bool = False) -> pa.Column:
    return _text(20, pa.Check.str_matches(CODE), unique=unique)


def _label() -> pa.Column:
    return _text(200, pa.Check.str_length(min_value=1))


def _assumption_explained(data: PolarsData) -> pl.LazyFrame:
    return data.lazyframe.select((pl.col("source") != "assumption") | (pl.col("rationale").str.len_chars() > 0))


def _schema(
    name: str,
    columns: dict[str, pa.Column],
    unique: list[str] | None = None,
    checks: pa.Check | None = None,
) -> pa.DataFrameSchema:
    return pa.DataFrameSchema(columns, checks=checks, strict=True, ordered=True, name=name, unique=unique)


REFERENCES = MappingProxyType(
    {
        "segment": _schema(
            "segment",
            {
                "segment_code": _code(unique=True),
                "lei_required": _text(1, pa.Check.isin(["Y", "N"])),
                "label": _label(),
            },
        ),
        "rating": _schema(
            "rating",
            {
                "rating_code": _code(unique=True),
                "rating_bucket": _code(),
                "rating_rank": _text(2, pa.Check.str_matches(r"^[1-9][0-9]?$"), unique=True),
            },
        ),
        "product": _schema(
            "product",
            {
                "product_code": _code(unique=True),
                "product_type": _text(20, pa.Check.isin(["ON_BALANCE", "OFF_BALANCE"])),
                "label": _label(),
            },
        ),
        "collateral_type": _schema("collateral_type", {"collateral_type": _code(unique=True), "label": _label()}),
        "country": _schema(
            "country",
            {"country_code": _text(2, pa.Check.str_matches(r"^[A-Z]{2}$"), unique=True), "label": _label()},
        ),
        "reason_code": _schema(
            "reason_code",
            {
                "reason_code": _text(3, pa.Check.str_matches(r"^[CR][0-9]{2}$"), unique=True),
                "feed": _text(20, pa.Check.isin(["counterparty", "exposure"])),
                "rule_text": _text(4000, pa.Check.str_length(min_value=1)),
            },
        ),
        "calibration": _schema(
            "calibration",
            {
                "parameter": _text(40, pa.Check.str_matches(r"^[a-z][a-z_]*$")),
                "key": _text(40, pa.Check.str_matches(r"^[A-Za-z0-9_.]*$")),
                "value": _text(20, pa.Check.str_matches(r"^[0-9]+(\.[0-9]+)?$")),
                "source": _text(400, pa.Check.str_length(min_value=1)),
                "rationale": _text(400),
            },
            unique=["parameter", "key"],
            checks=pa.Check(_assumption_explained, name="assumption_rationale"),
        ),
    }
)


def read_reference(ref_dir: Path, name: str) -> pl.DataFrame:
    if name not in REFERENCES:
        raise ContractError(f"unknown reference {name!r}")
    path = ref_dir / f"{name}.csv"
    try:
        frame = pl.read_csv(path, infer_schema=False)
    except (OSError, pl.exceptions.PolarsError) as error:
        raise ContractError(f"{path.name}: cannot read ({type(error).__name__})") from None
    return validate(REFERENCES[name], frame.with_columns(pl.all().fill_null("")), path.name)
