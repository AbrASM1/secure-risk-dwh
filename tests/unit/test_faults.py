from collections.abc import Mapping

import polars as pl
import pytest

from srdwh.config import Profile
from srdwh.generate.calibration import Calibration
from srdwh.generate.faults import (
    COUNTERPARTY_RULES,
    DUPLICATES,
    EXPOSURE_RULES,
    REASON,
    Variant,
    counterparty_faults,
    exposure_faults,
)
from srdwh.generate.lei import is_valid_lei
from srdwh.generate.rng import stream

LEGAL_ENTITIES = ["SOVEREIGN", "BANK", "CORPORATE"]
Faulted = tuple[pl.DataFrame, pl.DataFrame]


def inject(cpty: pl.DataFrame, expo: pl.DataFrame, profile: Profile, calibration: Calibration) -> Faulted:
    rng = stream(profile.seed, "fault")
    rates = dict(calibration.keyed("fault_rate_max").iter_rows())
    faulty_cpty = counterparty_faults(rng, cpty, profile.first_as_of, rates["counterparty"], LEGAL_ENTITIES)
    clean_ids = faulty_cpty.filter(pl.col(REASON).is_null())["cpty_id"]
    return faulty_cpty, exposure_faults(rng, expo, profile.first_as_of, rates["exposure"], clean_ids)


@pytest.fixture(scope="module")
def faulted(cpty_first: pl.DataFrame, expo_first: pl.DataFrame, profile: Profile, calibration: Calibration) -> Faulted:
    return inject(cpty_first, expo_first, profile, calibration)


def originals(faulty: pl.DataFrame, clean: pl.DataFrame) -> pl.DataFrame:
    return faulty.head(clean.height)


def test_every_rule_injected(faulted: Faulted) -> None:
    cpty, expo = faulted
    assert set(cpty[REASON].drop_nulls()) == set(COUNTERPARTY_RULES)
    assert set(expo[REASON].drop_nulls()) == set(EXPOSURE_RULES)


@pytest.mark.parametrize(
    ("index", "feed", "rules"), [(0, "counterparty", COUNTERPARTY_RULES), (1, "exposure", EXPOSURE_RULES)]
)
def test_fault_count_follows_rate(
    faulted: Faulted,
    cpty_first: pl.DataFrame,
    expo_first: pl.DataFrame,
    calibration: Calibration,
    index: int,
    feed: str,
    rules: Mapping[str, tuple[Variant, ...]],
) -> None:
    clean = (cpty_first, expo_first)[index]
    head = originals(faulted[index], clean)
    rate = dict(calibration.keyed("fault_rate_max").iter_rows())[feed]
    assert head[REASON].drop_nulls().len() == max(len(rules), int(rate * clean.height))
    assert faulted[index].height - clean.height == head[REASON].is_in(list(DUPLICATES)).sum()
    assert head.drop(REASON).columns == clean.columns


@pytest.mark.parametrize(("index", "rules"), [(0, COUNTERPARTY_RULES), (1, EXPOSURE_RULES)])
def test_faults_touch_only_rule_columns(
    faulted: Faulted,
    cpty_first: pl.DataFrame,
    expo_first: pl.DataFrame,
    profile: Profile,
    index: int,
    rules: Mapping[str, tuple[Variant, ...]],
) -> None:
    clean = (cpty_first, expo_first)[index]
    head = originals(faulted[index], clean)
    changed = pl.DataFrame({c: head[c] != clean[c] for c in clean.columns}).with_columns(head[REASON])
    assert not changed.filter(pl.col(REASON).is_null()).drop(REASON).select(pl.any_horizontal(pl.all()).any()).item()
    for code, variants in rules.items():
        allowed = {column for variant in variants for column in variant(profile.first_as_of)}
        rows = changed.filter(pl.col(REASON) == code).drop(REASON)
        touched = {c for c in rows.columns if rows[c].any()}
        assert touched <= allowed, code
        assert rows.select(pl.any_horizontal(pl.all()).all()).item() != (code in DUPLICATES), code


def test_duplicates_are_copies(faulted: Faulted, cpty_first: pl.DataFrame, expo_first: pl.DataFrame) -> None:
    for faulty, clean, key in ((faulted[0], cpty_first, "cpty_id"), (faulted[1], expo_first, "exposure_id")):
        copies = faulty.tail(faulty.height - clean.height).with_columns(pl.col(key).str.strip_chars_end())
        sources = originals(faulty, clean).filter(pl.col(REASON).is_in(list(DUPLICATES)))
        assert copies.sort(key).equals(sources.sort(key))


def test_lei_faults_on_legal_entities(faulted: Faulted) -> None:
    c06 = faulted[0].filter(pl.col(REASON) == "C06")
    assert c06["segment_code"].is_in(LEGAL_ENTITIES).all()
    assert not c06.select(is_valid_lei(pl.col("lei")).any()).item()


def test_exposure_faults_on_clean_counterparties(faulted: Faulted, expo_first: pl.DataFrame) -> None:
    cpty, expo = faulted
    clean_ids = cpty.filter(pl.col(REASON).is_null())["cpty_id"].implode()
    sources = expo_first.filter(originals(expo, expo_first)[REASON].is_not_null())
    assert sources["cpty_id"].is_in(clean_ids).all()


def test_faults_deterministic(
    faulted: Faulted, cpty_first: pl.DataFrame, expo_first: pl.DataFrame, profile: Profile, calibration: Calibration
) -> None:
    again = inject(cpty_first, expo_first, profile, calibration)
    assert again[0].equals(faulted[0])
    assert again[1].equals(faulted[1])


def test_too_few_rows_fail(cpty_first: pl.DataFrame, profile: Profile) -> None:
    with pytest.raises(ValueError, match="more eligible rows"):
        counterparty_faults(stream(1, "fault"), cpty_first.head(5), profile.first_as_of, 0.005, LEGAL_ENTITIES)
    with pytest.raises(ValueError, match="more eligible rows"):
        counterparty_faults(
            stream(1, "fault"),
            cpty_first.filter(pl.col("segment_code") == "RETAIL"),
            profile.first_as_of,
            0.005,
            LEGAL_ENTITIES,
        )
