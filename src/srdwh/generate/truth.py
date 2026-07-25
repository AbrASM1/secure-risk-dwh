from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from srdwh.contracts.feeds import FIELD_LENGTHS
from srdwh.contracts.reference import read_reference
from srdwh.generate.lei import is_valid_lei

REASON = "reason_code"
AMOUNT = r"^-?[0-9]{1,16}(\.[0-9]{1,2})?$"
ISO_DATE = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
FLAGS = ("Y", "N")
CURRENCY = "EUR"


@dataclass(frozen=True)
class Domains:
    segments: pl.Series
    lei_required: pl.Series
    ratings: pl.Series
    countries: pl.Series
    products: pl.Series
    collateral_types: pl.Series

    @classmethod
    def read(cls, ref_dir: Path) -> "Domains":
        segment = read_reference(ref_dir, "segment")
        return cls(
            segments=segment["segment_code"],
            lei_required=segment.filter(pl.col("lei_required") == "Y")["segment_code"],
            ratings=read_reference(ref_dir, "rating")["rating_code"],
            countries=read_reference(ref_dir, "country")["country_code"],
            products=read_reference(ref_dir, "product")["product_code"],
            collateral_types=read_reference(ref_dir, "collateral_type")["collateral_type"],
        )


def counterparty_reasons(frame: pl.DataFrame, as_of: date, domains: Domains) -> pl.Series:
    lei = _text("lei")
    rules = {
        "C01": _missing_or_long("cpty_id") | _missing_or_long("cpty_name"),
        "C02": _bad_date(as_of),
        "C03": _outside("segment_code", domains.segments),
        "C04": _outside("rating", domains.ratings),
        "C05": _outside("default_flag", pl.Series(FLAGS)),
        "C06": (lei.is_null() & ~_outside("segment_code", domains.lei_required))
        | (lei.is_not_null() & ~is_valid_lei(lei)),
        "C07": _outside("country", domains.countries),
        "C08": _duplicated("cpty_id"),
    }
    return frame.select(_first_failing(rules)).to_series()


def exposure_reasons(frame: pl.DataFrame, as_of: date, domains: Domains, accepted_cpty_ids: pl.Series) -> pl.Series:
    collateral, collateral_type, product = _text("collateral_amt"), _text("collateral_type"), _text("product_code")
    rules = {
        "R01": _missing_or_long("exposure_id") | _missing_or_long("cpty_id"),
        "R02": ~_amount("drawn_amt")
        | ~_amount("undrawn_amt")
        | (collateral.is_not_null() & ~_amount("collateral_amt")),
        "R03": (_value("drawn_amt") < 0) | (_value("undrawn_amt") < 0) | (_value("collateral_amt") < 0),
        "R04": _outside("product_code", domains.products),
        "R05": _bad_date(as_of),
        "R06": _duplicated("exposure_id"),
        "R07": _outside("cpty_id", accepted_cpty_ids),
        "R08": (_value("collateral_amt") > 0) & collateral_type.is_null(),
        "R09": collateral_type.is_not_null() & _outside("collateral_type", domains.collateral_types),
        "R10": ((product == "LOAN") & (_value("undrawn_amt") > 0))
        | ((product == "GUARANTEE") & (_value("drawn_amt") > 0)),
        "R11": _outside("currency", pl.Series([CURRENCY])),
    }
    return frame.select(_first_failing(rules)).to_series()


def accepted_ids(frame: pl.DataFrame, reasons: pl.Series) -> pl.Series:
    return frame.filter(reasons.is_null()).select(_text("cpty_id")).to_series()


def _first_failing(rules: Mapping[str, pl.Expr]) -> pl.Expr:
    return pl.coalesce([pl.when(failed.fill_null(False)).then(pl.lit(code)) for code, failed in rules.items()]).alias(
        REASON
    )


def _text(column: str) -> pl.Expr:
    trimmed = pl.col(column).str.strip_chars(" ")
    return pl.when(trimmed != "").then(trimmed)


def _missing_or_long(column: str) -> pl.Expr:
    return _text(column).is_null() | (_text(column).str.len_chars() > FIELD_LENGTHS[column])


def _outside(column: str, domain: pl.Series) -> pl.Expr:
    return ~_text(column).is_in(domain.implode()).fill_null(False)


def _bad_date(as_of: date) -> pl.Expr:
    value = _text("as_of_date")
    parsed = value.str.to_date("%Y-%m-%d", strict=False)
    return ~(value.str.contains(ISO_DATE) & (parsed == as_of)).fill_null(False)


def _duplicated(column: str) -> pl.Expr:
    return _text(column).is_not_null() & (pl.len().over(_text(column)) > 1)


def _amount(column: str) -> pl.Expr:
    return _text(column).str.contains(AMOUNT).fill_null(False)


def _value(column: str) -> pl.Expr:
    return _text(column).cast(pl.Decimal(20, 2), strict=False)
