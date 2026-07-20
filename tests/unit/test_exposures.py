from dataclasses import replace

import polars as pl
import pytest

from srdwh.config import Profile
from srdwh.contracts.feeds import FIELD_LENGTHS, validate_feed
from srdwh.generate.calibration import Calibration
from srdwh.generate.exposures import ExposureModel, exposures
from tests.unit.bounds import mean, within

AMOUNT = r"^[0-9]{1,16}\.[0-9]{2}$"


def cents(column: str) -> pl.Expr:
    return pl.col(column).str.replace(".", "", literal=True).cast(pl.Int64)


def continuing(panel: pl.DataFrame) -> pl.DataFrame:
    previous = panel.with_columns(
        pl.col("as_of_date").str.to_date().dt.offset_by("1mo").dt.month_end().cast(pl.Utf8).alias("as_of_date")
    )
    return panel.join(previous, on=["exposure_id", "as_of_date"], suffix="_before")


def test_exposures_match_contract(expo_panel: pl.DataFrame, cpty_first: pl.DataFrame, profile: Profile) -> None:
    assert validate_feed("exposure", expo_panel).height == profile.exposures * profile.as_of_count
    per_as_of = expo_panel.group_by("as_of_date").agg(pl.len(), pl.col("exposure_id").n_unique().alias("ids"))
    assert set(per_as_of["len"]) == set(per_as_of["ids"]) == {profile.exposures}
    assert expo_panel["cpty_id"].is_in(cpty_first["cpty_id"].implode()).all()
    assert (expo_panel["exposure_id"].str.len_chars() <= FIELD_LENGTHS["exposure_id"]).all()


def test_amounts_well_formed(expo_panel: pl.DataFrame) -> None:
    assert expo_panel["drawn_amt"].str.contains(AMOUNT).all()
    assert expo_panel["undrawn_amt"].str.contains(AMOUNT).all()
    secured = expo_panel.filter(pl.col("collateral_amt") != "")
    assert secured["collateral_amt"].str.contains(AMOUNT).all()
    assert (secured["collateral_type"] != "").all()
    assert (expo_panel.filter(pl.col("collateral_amt") == "")["collateral_type"] == "").all()
    assert set(expo_panel["currency"]) == {"EUR"}


def test_product_invariants(expo_panel: pl.DataFrame) -> None:
    assert set(expo_panel.filter(pl.col("product_code") == "LOAN")["undrawn_amt"]) == {"0.00"}
    assert set(expo_panel.filter(pl.col("product_code") == "GUARANTEE")["drawn_amt"]) == {"0.00"}
    lines = expo_panel.filter(pl.col("product_code") == "UNDRAWN_LINE")
    assert lines.select((cents("drawn_amt") > 0).any() & (cents("undrawn_amt") > 0).any()).item()


def test_book_persists_with_replacement(expo_panel: pl.DataFrame, profile: Profile, calibration: Calibration) -> None:
    kept = continuing(expo_panel)
    transitions = profile.exposures * (profile.as_of_count - 1)
    replaced = 1 - kept.height / transitions
    assert within(replaced, calibration.scalar("exposure_replacement_monthly"), transitions)
    for column in ("cpty_id", "product_code", "collateral_type"):
        assert (kept[column] == kept[f"{column}_before"]).all()


def test_amounts_drift_within_bound(expo_panel: pl.DataFrame, calibration: Calibration) -> None:
    drift = calibration.scalar("amount_drift_max")
    kept = continuing(expo_panel).with_columns(
        size=cents("drawn_amt") + cents("undrawn_amt"), before=cents("drawn_amt_before") + cents("undrawn_amt_before")
    )
    assert (kept["size"] - kept["before"]).abs().le(kept["before"] * drift + 2).all()
    assert mean(kept["size"] != kept["before"]) > 0.99


@pytest.mark.parametrize(("parameter", "column"), [("product_share", "product_code")])
def test_product_mix_follows_calibration(
    expo_first: pl.DataFrame, calibration: Calibration, parameter: str, column: str
) -> None:
    counts = expo_first[column].value_counts(normalize=True)
    observed = dict(zip(counts[column].to_list(), counts["proportion"].to_list(), strict=True))
    assert all(within(observed[k], p, expo_first.height) for k, p in calibration.keyed(parameter).iter_rows())


def test_collateral_follows_calibration(expo_first: pl.DataFrame, calibration: Calibration) -> None:
    secured = expo_first.filter(pl.col("collateral_amt") != "")
    assert within(secured.height / expo_first.height, calibration.scalar("collateral_share"), expo_first.height)
    counts = secured["collateral_type"].value_counts(normalize=True)
    observed = dict(zip(counts["collateral_type"].to_list(), counts["proportion"].to_list(), strict=True))
    shares = calibration.keyed("collateral_type_share").iter_rows()
    assert all(within(observed[k], p, secured.height) for k, p in shares)
    low, high = calibration.scalar("collateral_ratio_min"), calibration.scalar("collateral_ratio_max")
    ratio = secured.select(cents("collateral_amt") / (cents("drawn_amt") + cents("undrawn_amt"))).to_series()
    assert ratio.is_between(low - 0.001, high + 0.001).all()


def test_same_seed_same_exposures(profile: Profile, expo_model: ExposureModel, cpty_first: pl.DataFrame) -> None:
    small = replace(profile, exposures=500, as_of_count=3)
    ids, segments = cpty_first["cpty_id"], cpty_first["segment_code"]
    assert exposures(small, expo_model, ids, segments).equals(exposures(small, expo_model, ids, segments))
    assert not exposures(small, expo_model, ids, segments).equals(
        exposures(replace(small, seed=7), expo_model, ids, segments)
    )
