from dataclasses import replace
from datetime import date
from functools import cache
from math import sqrt
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from srdwh.config import Profile
from srdwh.contracts.feeds import FIELD_LENGTHS, validate_feed
from srdwh.contracts.reference import read_reference
from srdwh.contracts.validation import ContractError
from srdwh.generate.calibration import Calibration
from srdwh.generate.counterparties import CounterpartyModel, counterparties, counterparty_model
from srdwh.generate.lei import is_valid_lei
from srdwh.generate.names import FIRST_NAMES, LAST_NAMES

REF = Path(__file__).resolve().parents[2] / "db" / "ref"
PROFILE = Profile(
    name="test", seed=42, first_as_of=date(2025, 1, 31), as_of_count=12, counterparties=5_000, exposures=1
)
LEGAL_ENTITIES = ["SOVEREIGN", "BANK", "CORPORATE"]


@cache
def calibration() -> Calibration:
    return Calibration.read(REF)


@cache
def model() -> CounterpartyModel:
    return counterparty_model(calibration(), read_reference(REF, "rating"), read_reference(REF, "country"))


@cache
def panel() -> pl.DataFrame:
    return counterparties(PROFILE, model())


def first_month() -> pl.DataFrame:
    return panel().filter(pl.col("as_of_date") == PROFILE.first_as_of.isoformat())


def transitions() -> pl.DataFrame:
    ranks = read_reference(REF, "rating").select("rating_code", pl.col("rating_rank").cast(pl.Int32))
    return (
        panel()
        .join(ranks, left_on="rating", right_on="rating_code")
        .sort("cpty_id", "as_of_date")
        .with_columns(
            pl.col(c).shift(1).over("cpty_id").alias(f"previous_{c}")
            for c in ("rating", "rating_rank", "default_flag", "cpty_name")
        )
        .drop_nulls("previous_rating")
    )


def mean(series: pl.Series) -> float:
    return float(np.mean(series.cast(pl.Float64).to_numpy()))


def within(observed: float, expected: float, size: int) -> bool:
    return abs(observed - expected) <= 4 * sqrt(expected * (1 - expected) / size) + 1e-12


def test_counterparties_match_contract() -> None:
    frame = panel()
    assert validate_feed("counterparty", frame.drop("as_of_date").with_columns(frame["as_of_date"])).height
    per_as_of = frame.group_by("as_of_date").agg(pl.len(), pl.col("cpty_id").n_unique().alias("ids")).sort("as_of_date")
    assert per_as_of["as_of_date"].to_list() == [d.isoformat() for d in PROFILE.as_of_dates]
    assert set(per_as_of["len"]) == set(per_as_of["ids"]) == {PROFILE.counterparties}
    assert frame["cpty_id"].n_unique() == PROFILE.counterparties
    assert (frame["cpty_id"].str.len_chars() <= FIELD_LENGTHS["cpty_id"]).all()


def test_same_seed_same_counterparties() -> None:
    small = replace(PROFILE, counterparties=300, as_of_count=3)
    assert counterparties(small, model()).equals(counterparties(small, model()))
    assert not counterparties(small, model()).equals(counterparties(replace(small, seed=7), model()))


def test_lei_only_for_legal_entities() -> None:
    frame = panel().with_columns(has_lei=pl.col("lei") != "")
    by_segment = dict(first_month().group_by("segment_code").agg((pl.col("lei") != "").mean()).iter_rows())
    assert {s: by_segment[s] for s in [*LEGAL_ENTITIES, "RETAIL"]} == dict.fromkeys(LEGAL_ENTITIES, 1.0) | {
        "RETAIL": 0.0
    }
    sme = first_month().filter(pl.col("segment_code") == "SME")
    assert within(by_segment["SME"], 0.5, sme.height)
    assert frame.filter("has_lei").select(is_valid_lei(pl.col("lei")).all()).item()
    assert frame.group_by("cpty_id").agg(pl.col("lei").n_unique())["lei"].max() == 1
    assert first_month().filter(pl.col("lei") != "")["lei"].is_unique().all()


@pytest.mark.parametrize(("parameter", "column"), [("segment_share", "segment_code"), ("country_share", "country")])
def test_mix_follows_calibration(parameter: str, column: str) -> None:
    counts = first_month()[column].value_counts(normalize=True)
    observed = dict(zip(counts[column].to_list(), counts["proportion"].to_list(), strict=True))
    expected = dict(calibration().keyed(parameter).iter_rows())
    assert set(observed) <= set(expected)
    assert all(within(observed.get(k, 0.0), p, PROFILE.counterparties) for k, p in expected.items())


def test_ratings_by_segment() -> None:
    month = first_month()
    assert set(month.filter(pl.col("segment_code") == "RETAIL")["rating"]) == {"NR"}
    assert "NR" not in set(month.filter(pl.col("segment_code").is_in(["SOVEREIGN", "BANK"]))["rating"])


def test_initial_defaults_follow_annual_rates() -> None:
    rates = calibration().keyed("default_rate_annual").rename({"key": "rating", "value": "rate"})
    month = first_month().join(rates, on="rating")
    assert within(mean(month["default_flag"] == "Y"), mean(month["rate"]), month.height)
    assert month.filter(pl.col("rating") == "AAA")["default_flag"].to_list().count("Y") == 0


def test_migrations_one_notch_within_scale() -> None:
    frame = transitions()
    moved = frame.filter(pl.col("rating") != pl.col("previous_rating"))
    assert moved.height > 0
    assert ((moved["rating_rank"] - moved["previous_rating_rank"]).abs() == 1).all()
    assert not moved["rating"].is_in(["NR"]).any()
    assert not moved["previous_rating"].is_in(["NR"]).any()
    assert (moved["previous_default_flag"] == "N").all()
    eligible = frame.filter((pl.col("previous_default_flag") == "N") & (pl.col("previous_rating") != "NR"))
    assert within(moved.height / eligible.height, 0.01, eligible.height)


def test_defaults_occur_and_cure() -> None:
    frame = transitions()
    was_defaulted = frame.filter(pl.col("previous_default_flag") == "Y")
    assert within(mean(was_defaulted["default_flag"] == "N"), 1 / 12, was_defaulted.height)
    assert frame.filter((pl.col("previous_default_flag") == "N") & (pl.col("default_flag") == "Y")).height > 0


def test_name_changes_rare() -> None:
    frame = transitions()
    changed = mean(frame["cpty_name"] != frame["previous_cpty_name"])
    assert 0 < changed <= 0.002


def test_names_by_segment() -> None:
    month = first_month()
    retail = month.filter(pl.col("segment_code") == "RETAIL")["cpty_name"].str.split_exact(" ", 1).struct.unnest()
    assert retail["field_0"].is_in(FIRST_NAMES.tolist()).all()
    assert retail["field_1"].is_in(LAST_NAMES.tolist()).all()
    assert month.filter(pl.col("segment_code") == "SOVEREIGN")["cpty_name"].str.starts_with("Government of ").all()
    assert month.filter(pl.col("segment_code") == "BANK")["cpty_name"].str.contains(" Bank ").all()
    assert panel()["cpty_name"].str.len_chars().is_between(1, FIELD_LENGTHS["cpty_name"]).all()


def test_calibration_accessors_fail_fast() -> None:
    with pytest.raises(ContractError, match="missing parameter"):
        calibration().keyed("absent")
    with pytest.raises(ContractError, match="not a scalar"):
        calibration().scalar("segment_share")
    with pytest.raises(ContractError, match="lacks OTHER"):
        calibration().aligned("segment_share", ["RETAIL", "OTHER"])


def test_model_rejects_inconsistent_reference() -> None:
    ratings = read_reference(REF, "rating").with_columns(
        pl.when(pl.col("rating_code") == "NR").then(pl.lit("0")).otherwise("rating_rank").alias("rating_rank")
    )
    with pytest.raises(ContractError, match="last rank"):
        counterparty_model(calibration(), ratings, read_reference(REF, "country"))
    with pytest.raises(ContractError, match=r"outside country\.csv"):
        counterparty_model(calibration(), read_reference(REF, "rating"), read_reference(REF, "country").head(3))
