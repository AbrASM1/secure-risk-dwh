from pathlib import Path

import polars as pl
import pytest

from srdwh.generate.lei import ALPHABET, is_valid_lei, with_check_digits

SAMPLE = Path(__file__).resolve().parents[2] / "db" / "tests" / "fixtures" / "lei_gleif_sample.csv"


def sample() -> pl.DataFrame:
    return pl.read_csv(SAMPLE, infer_schema=False)


def test_gleif_sample_valid() -> None:
    codes = sample()
    assert codes.height == 1_000
    assert codes.select(is_valid_lei(pl.col("lei")).all()).item()


def single_char_variants() -> pl.DataFrame:
    return (
        sample()
        .join(pl.DataFrame({"position": range(20)}), how="cross")
        .join(pl.DataFrame({"replacement": list(ALPHABET)}), how="cross")
        .with_columns(original=pl.col("lei").str.slice(pl.col("position"), 1))
        .filter(pl.col("replacement") != pl.col("original"))
        .select(
            pl.concat_str(
                pl.col("lei").str.slice(0, pl.col("position")),
                pl.col("replacement"),
                pl.col("lei").str.slice(pl.col("position") + 1),
            ).alias("variant"),
            (pl.col("original").str.contains("[0-9]") == pl.col("replacement").str.contains("[0-9]")).alias(
                "same_class"
            ),
        )
        .with_columns(valid=is_valid_lei(pl.col("variant")))
    )


def test_one_char_change_invalid() -> None:
    variants = single_char_variants()
    assert variants.height == 1_000 * 20 * 35
    same_class = variants.filter(pl.col("same_class"))
    assert same_class.height > 0
    assert not same_class["valid"].any()


def test_cross_class_change_limit_matches_spec() -> None:
    assert single_char_variants().filter(pl.col("valid"))["same_class"].value_counts().rows() == [(False, 3_540)]


def test_check_digits_match_gleif() -> None:
    codes = sample().select(pl.col("lei"), with_check_digits(pl.col("lei").str.slice(0, 18)).alias("rebuilt"))
    assert (codes["lei"] == codes["rebuilt"]).all()


@pytest.mark.parametrize(
    "code",
    ["", "529900t8bm49aursdo55", "529900T8BM49AURSDO5", "529900T8BM49AURSDO555", "529900T8BM49AURSDOA5", None],
)
def test_malformed_code_invalid(code: str | None) -> None:
    assert not pl.select(is_valid_lei(pl.lit(code, pl.Utf8))).item()
