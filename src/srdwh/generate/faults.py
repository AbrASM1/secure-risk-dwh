from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from types import MappingProxyType

import numpy as np
import polars as pl

from srdwh.contracts.feeds import FIELD_LENGTHS
from srdwh.generate.lei import ALPHABET

Variant = Callable[[date], Mapping[str, pl.Expr]]
REASON = "reason_code"
DUPLICATES = frozenset({"C08", "R06"})
ORPHAN_CPTY_ID = "CP99999999"
_NEXT_SAME_CLASS = {
    c: ALPHABET[(i + 1) % 10] if i < 10 else ALPHABET[10 + (i - 9) % 26] for i, c in enumerate(ALPHABET)
}


def _set(column: str, value: str) -> Variant:
    return lambda as_of: {column: pl.lit(value)}


def _change(column: str, expression: pl.Expr) -> Variant:
    return lambda as_of: {column: expression}


def _dates(column: str) -> tuple[Variant, ...]:
    return (
        lambda as_of: {column: pl.lit(f"{as_of.year}-02-30")},
        lambda as_of: {column: pl.lit(as_of.strftime("%d/%m/%Y"))},
        lambda as_of: {column: pl.lit((as_of.replace(day=1) - timedelta(days=1)).isoformat())},
    )


def _too_long(column: str) -> Variant:
    return _change(column, pl.col(column).str.pad_end(FIELD_LENGTHS[column] + 1, "X"))


def _lei_check_broken() -> pl.Expr:
    lei = pl.col("lei")
    shifted = lei.str.slice(10, 1).replace_strict(_NEXT_SAME_CLASS, return_dtype=pl.Utf8)
    return pl.concat_str(lei.str.slice(0, 10), shifted, lei.str.slice(11))


COUNTERPARTY_RULES: Mapping[str, tuple[Variant, ...]] = MappingProxyType(
    {
        "C01": (_set("cpty_id", ""), _set("cpty_id", "   "), _too_long("cpty_id"), _too_long("cpty_name")),
        "C02": _dates("as_of_date"),
        "C03": (_change("segment_code", pl.col("segment_code").str.to_lowercase()), _set("segment_code", "")),
        "C04": (_set("rating", "C"), _change("rating", pl.col("rating").str.to_lowercase())),
        "C05": (_set("default_flag", "y"), _set("default_flag", "")),
        "C06": (_set("lei", ""), _change("lei", pl.col("lei").str.to_lowercase()), _change("lei", _lei_check_broken())),
        "C07": (_change("country", pl.col("country").str.to_lowercase()), _set("country", "FRA"), _set("country", "")),
        "C08": (_change("cpty_id", pl.col("cpty_id")), _change("cpty_id", pl.concat_str("cpty_id", pl.lit(" ")))),
    }
)
EXPOSURE_RULES: Mapping[str, tuple[Variant, ...]] = MappingProxyType(
    {
        "R01": (_set("exposure_id", ""), _too_long("exposure_id"), _set("cpty_id", "")),
        "R02": (
            _set("drawn_amt", "1e3"),
            _set("drawn_amt", "1,50"),
            _set("drawn_amt", "1.505"),
            _set("drawn_amt", "1" * 17),
            _set("collateral_amt", "abc"),
        ),
        "R03": (
            _set("drawn_amt", "-0.01"),
            lambda as_of: {"collateral_amt": pl.lit("-5.00"), "collateral_type": pl.lit("CASH")},
        ),
        "R04": (
            _change("product_code", pl.col("product_code").str.to_lowercase()),
            _set("product_code", "MORTGAGE"),
            _set("product_code", ""),
        ),
        "R05": _dates("as_of_date"),
        "R06": (
            _change("exposure_id", pl.col("exposure_id")),
            _change("exposure_id", pl.concat_str("exposure_id", pl.lit(" "))),
        ),
        "R07": (_set("cpty_id", ORPHAN_CPTY_ID),),
        "R08": (lambda as_of: {"collateral_amt": pl.lit("0.01"), "collateral_type": pl.lit("")},),
        "R09": (_set("collateral_type", "GOLD"), _set("collateral_type", "cash")),
        "R10": (
            lambda as_of: {"product_code": pl.lit("LOAN"), "undrawn_amt": pl.lit("0.01")},
            lambda as_of: {"product_code": pl.lit("GUARANTEE"), "drawn_amt": pl.lit("0.01")},
        ),
        "R11": (_set("currency", "USD"), _set("currency", "eur")),
    }
)


def counterparty_faults(
    rng: np.random.Generator, frame: pl.DataFrame, as_of: date, rate: float, legal_segments: Sequence[str]
) -> pl.DataFrame:
    legal = pl.col("segment_code").is_in(list(legal_segments))
    return _inject(rng, frame, COUNTERPARTY_RULES, as_of, rate, pl.lit(True), (frozenset({"C06"}), legal))


def exposure_faults(
    rng: np.random.Generator, frame: pl.DataFrame, as_of: date, rate: float, clean_cpty_ids: pl.Series
) -> pl.DataFrame:
    eligible = pl.col("cpty_id").is_in(clean_cpty_ids.implode())
    return _inject(rng, frame, EXPOSURE_RULES, as_of, rate, eligible, (frozenset(), pl.lit(False)))


def _inject(
    rng: np.random.Generator,
    frame: pl.DataFrame,
    rules: Mapping[str, tuple[Variant, ...]],
    as_of: date,
    rate: float,
    eligible: pl.Expr,
    restricted: tuple[frozenset[str], pl.Expr],
) -> pl.DataFrame:
    events = _events(rng, rules, max(len(rules), int(rate * frame.height)))
    marked = frame.with_row_index("_row").join(
        _rows(rng, frame, events, eligible, restricted), on="_row", how="left", maintain_order="left"
    )
    in_place = {code: variants for code, variants in rules.items() if code not in DUPLICATES}
    copies = {code: variants for code, variants in rules.items() if code in DUPLICATES}
    return pl.concat(
        [
            marked.with_columns(_mutations(in_place, as_of, frame.columns)),
            marked.filter(pl.col(REASON).is_in(list(copies))).with_columns(_mutations(copies, as_of, frame.columns)),
        ]
    ).select(*frame.columns, REASON)


def _events(rng: np.random.Generator, rules: Mapping[str, tuple[Variant, ...]], count: int) -> pl.DataFrame:
    codes = np.array(sorted(rules))
    drawn = np.concatenate([codes, rng.choice(codes, size=count - codes.shape[0])])
    variants = np.array([len(rules[code]) for code in codes])[np.searchsorted(codes, drawn)]
    return pl.DataFrame({REASON: drawn, "_variant": (rng.random(count) * variants).astype(np.int64)})


def _rows(
    rng: np.random.Generator,
    frame: pl.DataFrame,
    events: pl.DataFrame,
    eligible: pl.Expr,
    restricted: tuple[frozenset[str], pl.Expr],
) -> pl.DataFrame:
    codes, condition = restricted
    candidates = (
        frame.with_row_index("_row")
        .with_columns(_priority=pl.Series(rng.permutation(frame.height)), _restricted=condition)
        .filter(eligible)
        .sort("_priority")
    )
    first = events.filter(pl.col(REASON).is_in(list(codes)))
    rest = events.filter(~pl.col(REASON).is_in(list(codes)))
    chosen = candidates.filter("_restricted").head(first.height)
    others = candidates.join(chosen, on="_row", how="anti").head(rest.height)
    if chosen.height < first.height or others.height < rest.height:
        raise ValueError(f"{events.height} faults need more eligible rows than the {candidates.height} available")
    return pl.concat(
        [
            pl.concat([first, chosen.select("_row")], how="horizontal"),
            pl.concat([rest, others.select("_row")], how="horizontal"),
        ]
    )


def _mutations(rules: Mapping[str, tuple[Variant, ...]], as_of: date, columns: Sequence[str]) -> list[pl.Expr]:
    changes = [
        (code, number, column, expression)
        for code, variants in rules.items()
        for number, variant in enumerate(variants)
        for column, expression in variant(as_of).items()
    ]
    return [_column(column, [(c, n, e) for c, n, col, e in changes if col == column]) for column in columns]


def _column(column: str, changes: list[tuple[str, int, pl.Expr]]) -> pl.Expr:
    expression = pl.col(column)
    for code, number, value in changes:
        expression = (
            pl.when((pl.col(REASON) == code) & (pl.col("_variant") == number)).then(value).otherwise(expression)
        )
    return expression.alias(column)
