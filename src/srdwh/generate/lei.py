from functools import reduce

import polars as pl

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
LEI_PATTERN = r"^[A-Z0-9]{18}[0-9]{2}$"
LEI_LENGTH = 20
_VALUES = {character: value for value, character in enumerate(ALPHABET)}


def _mod97(code: pl.Expr) -> pl.Expr:
    def step(remainder: pl.Expr, position: int) -> pl.Expr:
        value = code.str.slice(position, 1).replace_strict(_VALUES, default=None, return_dtype=pl.Int64)
        return (remainder * pl.when(value < 10).then(10).otherwise(100) + value) % 97

    return reduce(step, range(LEI_LENGTH), pl.lit(0, pl.Int64))


def is_valid_lei(code: pl.Expr) -> pl.Expr:
    return (code.str.contains(LEI_PATTERN) & (_mod97(code) == 1)).fill_null(False)


def with_check_digits(base: pl.Expr) -> pl.Expr:
    check = pl.lit(98, pl.Int64) - _mod97(pl.concat_str(base, pl.lit("00")))
    return pl.concat_str(base, check.cast(pl.Utf8).str.zfill(2))
