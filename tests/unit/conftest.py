from datetime import date
from pathlib import Path

import polars as pl
import pytest

from srdwh.config import Profile
from srdwh.contracts.reference import read_reference
from srdwh.generate.calibration import Calibration
from srdwh.generate.counterparties import CounterpartyModel, counterparties, counterparty_model
from srdwh.generate.exposures import ExposureModel, exposure_model, exposures

REF = Path(__file__).resolve().parents[2] / "db" / "ref"


@pytest.fixture(scope="session")
def ref_dir() -> Path:
    return REF


@pytest.fixture(scope="session")
def calibration() -> Calibration:
    return Calibration.read(REF)


@pytest.fixture(scope="session")
def profile() -> Profile:
    return Profile(
        name="test", seed=42, first_as_of=date(2025, 1, 31), as_of_count=12, counterparties=5_000, exposures=50_000
    )


@pytest.fixture(scope="session")
def cpty_model(calibration: Calibration) -> CounterpartyModel:
    return counterparty_model(calibration, read_reference(REF, "rating"), read_reference(REF, "country"))


@pytest.fixture(scope="session")
def expo_model(calibration: Calibration, cpty_model: CounterpartyModel) -> ExposureModel:
    return exposure_model(calibration, cpty_model.segments)


@pytest.fixture(scope="session")
def cpty_panel(profile: Profile, cpty_model: CounterpartyModel) -> pl.DataFrame:
    return counterparties(profile, cpty_model)


@pytest.fixture(scope="session")
def expo_panel(profile: Profile, expo_model: ExposureModel, cpty_panel: pl.DataFrame) -> pl.DataFrame:
    first = first_as_of(cpty_panel, profile)
    return exposures(profile, expo_model, first["cpty_id"], first["segment_code"])


def first_as_of(panel: pl.DataFrame, profile: Profile) -> pl.DataFrame:
    return panel.filter(pl.col("as_of_date") == profile.first_as_of.isoformat())


@pytest.fixture(scope="session")
def cpty_first(cpty_panel: pl.DataFrame, profile: Profile) -> pl.DataFrame:
    return first_as_of(cpty_panel, profile)


@pytest.fixture(scope="session")
def expo_first(expo_panel: pl.DataFrame, profile: Profile) -> pl.DataFrame:
    return first_as_of(expo_panel, profile)
