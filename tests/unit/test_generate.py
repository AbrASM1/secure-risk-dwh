from dataclasses import replace
from pathlib import Path

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
from tests.unit.bounds import mean, within

LEGAL_ENTITIES = ["SOVEREIGN", "BANK", "CORPORATE"]


def transitions(panel: pl.DataFrame, ref_dir: Path) -> pl.DataFrame:
    ranks = read_reference(ref_dir, "rating").select("rating_code", pl.col("rating_rank").cast(pl.Int32))
    return (
        panel.join(ranks, left_on="rating", right_on="rating_code")
        .sort("cpty_id", "as_of_date")
        .with_columns(
            pl.col(c).shift(1).over("cpty_id").alias(f"previous_{c}")
            for c in ("rating", "rating_rank", "default_flag", "cpty_name")
        )
        .drop_nulls("previous_rating")
    )


def test_counterparties_match_contract(cpty_panel: pl.DataFrame, profile: Profile) -> None:
    assert validate_feed("counterparty", cpty_panel).height == profile.counterparties * profile.as_of_count
    per_as_of = cpty_panel.group_by("as_of_date").agg(pl.len(), pl.col("cpty_id").n_unique().alias("ids"))
    assert sorted(per_as_of["as_of_date"]) == [d.isoformat() for d in profile.as_of_dates]
    assert set(per_as_of["len"]) == set(per_as_of["ids"]) == {profile.counterparties}
    assert cpty_panel["cpty_id"].n_unique() == profile.counterparties
    assert (cpty_panel["cpty_id"].str.len_chars() <= FIELD_LENGTHS["cpty_id"]).all()


def test_same_seed_same_counterparties(profile: Profile, cpty_model: CounterpartyModel) -> None:
    small = replace(profile, counterparties=300, as_of_count=3)
    assert counterparties(small, cpty_model).equals(counterparties(small, cpty_model))
    assert not counterparties(small, cpty_model).equals(counterparties(replace(small, seed=7), cpty_model))


def test_lei_only_for_legal_entities(cpty_panel: pl.DataFrame, cpty_first: pl.DataFrame) -> None:
    by_segment = dict(cpty_first.group_by("segment_code").agg((pl.col("lei") != "").mean()).iter_rows())
    assert {s: by_segment[s] for s in [*LEGAL_ENTITIES, "RETAIL"]} == dict.fromkeys(LEGAL_ENTITIES, 1.0) | {
        "RETAIL": 0.0
    }
    assert within(by_segment["SME"], 0.5, cpty_first.filter(pl.col("segment_code") == "SME").height)
    assert cpty_panel.filter(pl.col("lei") != "").select(is_valid_lei(pl.col("lei")).all()).item()
    assert cpty_panel.group_by("cpty_id").agg(pl.col("lei").n_unique())["lei"].max() == 1
    assert cpty_first.filter(pl.col("lei") != "")["lei"].is_unique().all()


@pytest.mark.parametrize(("parameter", "column"), [("segment_share", "segment_code"), ("country_share", "country")])
def test_mix_follows_calibration(
    cpty_first: pl.DataFrame, calibration: Calibration, parameter: str, column: str
) -> None:
    counts = cpty_first[column].value_counts(normalize=True)
    observed = dict(zip(counts[column].to_list(), counts["proportion"].to_list(), strict=True))
    expected = dict(calibration.keyed(parameter).iter_rows())
    assert set(observed) <= set(expected)
    assert all(within(observed.get(k, 0.0), p, cpty_first.height) for k, p in expected.items())


def test_ratings_by_segment(cpty_first: pl.DataFrame) -> None:
    assert set(cpty_first.filter(pl.col("segment_code") == "RETAIL")["rating"]) == {"NR"}
    assert "NR" not in set(cpty_first.filter(pl.col("segment_code").is_in(["SOVEREIGN", "BANK"]))["rating"])


def test_initial_defaults_follow_annual_rates(cpty_first: pl.DataFrame, calibration: Calibration) -> None:
    rates = calibration.keyed("default_rate_annual").rename({"key": "rating", "value": "rate"})
    month = cpty_first.join(rates, on="rating")
    assert within(mean(month["default_flag"] == "Y"), mean(month["rate"]), month.height)
    assert month.filter(pl.col("rating") == "AAA")["default_flag"].to_list().count("Y") == 0


def test_migrations_one_notch_within_scale(cpty_panel: pl.DataFrame, ref_dir: Path) -> None:
    frame = transitions(cpty_panel, ref_dir)
    moved = frame.filter(pl.col("rating") != pl.col("previous_rating"))
    assert moved.height > 0
    assert ((moved["rating_rank"] - moved["previous_rating_rank"]).abs() == 1).all()
    assert not moved["rating"].is_in(["NR"]).any()
    assert not moved["previous_rating"].is_in(["NR"]).any()
    assert (moved["previous_default_flag"] == "N").all()
    eligible = frame.filter((pl.col("previous_default_flag") == "N") & (pl.col("previous_rating") != "NR"))
    assert within(moved.height / eligible.height, 0.01, eligible.height)


def test_defaults_occur_and_cure(cpty_panel: pl.DataFrame, ref_dir: Path) -> None:
    frame = transitions(cpty_panel, ref_dir)
    was_defaulted = frame.filter(pl.col("previous_default_flag") == "Y")
    assert within(mean(was_defaulted["default_flag"] == "N"), 1 / 12, was_defaulted.height)
    assert frame.filter((pl.col("previous_default_flag") == "N") & (pl.col("default_flag") == "Y")).height > 0


def test_name_changes_rare(cpty_panel: pl.DataFrame, ref_dir: Path) -> None:
    frame = transitions(cpty_panel, ref_dir)
    changed = mean(frame["cpty_name"] != frame["previous_cpty_name"])
    assert 0 < changed <= 0.002


def test_names_by_segment(cpty_panel: pl.DataFrame, cpty_first: pl.DataFrame) -> None:
    retail = cpty_first.filter(pl.col("segment_code") == "RETAIL")["cpty_name"].str.split_exact(" ", 1).struct.unnest()
    assert retail["field_0"].is_in(FIRST_NAMES.tolist()).all()
    assert retail["field_1"].is_in(LAST_NAMES.tolist()).all()
    assert cpty_first.filter(pl.col("segment_code") == "SOVEREIGN")["cpty_name"].str.starts_with("Government of ").all()
    assert cpty_first.filter(pl.col("segment_code") == "BANK")["cpty_name"].str.contains(" Bank ").all()
    assert cpty_panel["cpty_name"].str.len_chars().is_between(1, FIELD_LENGTHS["cpty_name"]).all()


def test_calibration_accessors_fail_fast(calibration: Calibration) -> None:
    with pytest.raises(ContractError, match="missing parameter"):
        calibration.keyed("absent")
    with pytest.raises(ContractError, match="not a scalar"):
        calibration.scalar("segment_share")
    with pytest.raises(ContractError, match="lacks OTHER"):
        calibration.aligned("segment_share", ["RETAIL", "OTHER"])


def test_model_rejects_inconsistent_reference(calibration: Calibration, ref_dir: Path) -> None:
    ratings = read_reference(ref_dir, "rating").with_columns(
        pl.when(pl.col("rating_code") == "NR").then(pl.lit("0")).otherwise("rating_rank").alias("rating_rank")
    )
    with pytest.raises(ContractError, match="last rank"):
        counterparty_model(calibration, ratings, read_reference(ref_dir, "country"))
    with pytest.raises(ContractError, match=r"outside country\.csv"):
        counterparty_model(calibration, read_reference(ref_dir, "rating"), read_reference(ref_dir, "country").head(3))
