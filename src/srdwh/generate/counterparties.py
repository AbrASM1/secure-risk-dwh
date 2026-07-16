from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

from srdwh.config import Profile
from srdwh.contracts.feeds import COUNTERPARTY_COLUMNS
from srdwh.contracts.validation import ContractError
from srdwh.generate.calibration import Calibration
from srdwh.generate.lei import ALPHABET, with_check_digits
from srdwh.generate.names import names
from srdwh.generate.rng import categorical, cumulative, stream

UNRATED = "NR"
LEI_BASE_LENGTH = 18
_ASCII = np.frombuffer(ALPHABET.encode("ascii"), dtype=np.uint8)


@dataclass(frozen=True)
class CounterpartyModel:
    segments: np.ndarray
    segment_cumulative: np.ndarray
    lei_share: np.ndarray
    ratings: np.ndarray
    rating_cumulative: np.ndarray
    annual_default: np.ndarray
    countries: np.ndarray
    country_labels: np.ndarray
    country_cumulative: np.ndarray
    migration: float
    downgrade: float
    cure: float
    name_change: float

    @property
    def scale_size(self) -> int:
        return int(self.ratings.shape[0]) - 1

    @property
    def monthly_default(self) -> np.ndarray:
        return 1 - (1 - self.annual_default) ** (1 / 12)


@dataclass(frozen=True)
class _Population:
    cpty_id: pl.Series
    lei: pl.Series
    segment: np.ndarray
    country: np.ndarray


@dataclass(frozen=True)
class _State:
    rating: np.ndarray
    defaulted: np.ndarray
    name: pl.Series


def counterparty_model(calibration: Calibration, ratings: pl.DataFrame, countries: pl.DataFrame) -> CounterpartyModel:
    rating_codes = ratings.sort(pl.col("rating_rank").cast(pl.Int32))["rating_code"].to_numpy()
    if rating_codes[-1] != UNRATED:
        raise ContractError(f"rating: {UNRATED} must have the last rank")
    shares = calibration.keyed("segment_share")
    segments = shares["key"].to_numpy()
    country_shares = calibration.keyed("country_share").join(
        countries, left_on="key", right_on="country_code", how="left", maintain_order="left"
    )
    if country_shares["label"].null_count():
        raise ContractError("calibration: country_share holds a code outside country.csv")
    rating_share = calibration.aligned("rating_share", [f"{s}.{r}" for s in segments for r in rating_codes])
    return CounterpartyModel(
        segments=segments,
        segment_cumulative=cumulative(shares["value"].to_numpy()),
        lei_share=calibration.aligned("lei_share", segments.tolist()),
        ratings=rating_codes,
        rating_cumulative=cumulative(rating_share.reshape(segments.shape[0], rating_codes.shape[0])),
        annual_default=calibration.aligned("default_rate_annual", rating_codes.tolist()),
        countries=country_shares["key"].to_numpy(),
        country_labels=country_shares["label"].to_numpy(),
        country_cumulative=cumulative(country_shares["value"].to_numpy()),
        migration=calibration.scalar("rating_migration_monthly"),
        downgrade=calibration.scalar("rating_downgrade_share"),
        cure=1 / calibration.scalar("default_duration_months"),
        name_change=calibration.scalar("name_change_monthly"),
    )


def counterparties(profile: Profile, model: CounterpartyModel) -> pl.DataFrame:
    rng = stream(profile.seed, "counterparty")
    population = _population(rng, model, profile.counterparties)
    state = _initial_state(rng, model, population)
    frames = []
    for month, as_of in enumerate(profile.as_of_dates):
        state = _next_month(rng, model, population, state) if month else state
        frames.append(_feed(model, population, state, as_of))
    return pl.concat(frames)


def _population(rng: np.random.Generator, model: CounterpartyModel, size: int) -> _Population:
    segment = categorical(rng.random(size), model.segment_cumulative)
    country = categorical(rng.random(size), model.country_cumulative)
    has_lei = rng.random(size) < model.lei_share[segment]
    bases = _ASCII[rng.integers(_ASCII.shape[0], size=(size, LEI_BASE_LENGTH))]
    lei = pl.DataFrame(
        {"base": np.char.decode(bases.view(f"S{LEI_BASE_LENGTH}").ravel(), "ascii"), "has_lei": has_lei}
    ).select(pl.when("has_lei").then(with_check_digits(pl.col("base"))).otherwise(pl.lit("")).alias("lei"))
    cpty_id = pl.select(pl.format("CP{}", pl.int_range(1, size + 1).cast(pl.Utf8).str.zfill(8)).alias("cpty_id"))
    return _Population(cpty_id.to_series(), lei.to_series(), segment, country)


def _initial_state(rng: np.random.Generator, model: CounterpartyModel, population: _Population) -> _State:
    size = int(population.segment.shape[0])
    rating = categorical(rng.random(size), model.rating_cumulative[population.segment])
    defaulted = rng.random(size) < model.annual_default[rating]
    return _State(rating, defaulted, _names(rng, model, population))


def _next_month(rng: np.random.Generator, model: CounterpartyModel, population: _Population, state: _State) -> _State:
    size = int(population.segment.shape[0])
    move, down, default, rename = (rng.random(size) for _ in range(4))
    migrating = ~state.defaulted & (state.rating < model.scale_size) & (move < model.migration)
    step = np.where(down < model.downgrade, 1, -1)
    rating = np.where(migrating, np.clip(state.rating + step, 0, model.scale_size - 1), state.rating)
    defaulted = np.where(state.defaulted, default >= model.cure, default < model.monthly_default[rating])
    renamed = pl.Series(rename < model.name_change)
    return _State(rating, defaulted, _names(rng, model, population).zip_with(renamed, state.name))


def _names(rng: np.random.Generator, model: CounterpartyModel, population: _Population) -> pl.Series:
    return names(rng, model.segments[population.segment], model.country_labels[population.country])


def _feed(model: CounterpartyModel, population: _Population, state: _State, as_of: date) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "cpty_id": population.cpty_id,
            "cpty_name": state.name,
            "lei": population.lei,
            "segment_code": model.segments[population.segment],
            "country": model.countries[population.country],
            "rating": model.ratings[state.rating],
            "default_flag": np.where(state.defaulted, "Y", "N"),
            "as_of_date": np.full(population.segment.shape[0], as_of.isoformat()),
        },
        schema=dict.fromkeys(COUNTERPARTY_COLUMNS, pl.Utf8),
    )
