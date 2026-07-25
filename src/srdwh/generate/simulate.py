from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from srdwh.config import Profile
from srdwh.contracts.reference import read_reference
from srdwh.generate.calibration import Calibration
from srdwh.generate.counterparties import counterparties, counterparty_model
from srdwh.generate.exposures import exposure_model, exposures
from srdwh.generate.faults import counterparty_faults, exposure_faults
from srdwh.generate.rng import stream
from srdwh.generate.truth import REASON, Domains, accepted_ids, counterparty_reasons, exposure_reasons

IDS = {"counterparty": "cpty_id", "exposure": "exposure_id"}


@dataclass(frozen=True)
class Partition:
    feed: str
    as_of: date
    rows: pl.DataFrame
    expected: pl.DataFrame
    injected: pl.Series


@dataclass(frozen=True)
class _Inputs:
    counterparties: pl.DataFrame
    exposures: pl.DataFrame
    domains: Domains
    rates: np.ndarray


def simulate(profile: Profile, ref_dir: Path) -> Iterator[Partition]:
    inputs = _inputs(profile, ref_dir)
    rng = stream(profile.seed, "fault")
    for as_of in profile.as_of_dates:
        yield from _partitions(rng, inputs, as_of)


def _inputs(profile: Profile, ref_dir: Path) -> _Inputs:
    calibration = Calibration.read(ref_dir)
    model = counterparty_model(calibration, read_reference(ref_dir, "rating"), read_reference(ref_dir, "country"))
    panel = counterparties(profile, model)
    first = panel.filter(pl.col("as_of_date") == profile.first_as_of.isoformat())
    book = exposures(profile, exposure_model(calibration, model.segments), first["cpty_id"], first["segment_code"])
    rates = calibration.aligned("fault_rate_max", list(IDS))
    return _Inputs(panel, book, Domains.read(ref_dir), rates)


def _partitions(rng: np.random.Generator, inputs: _Inputs, as_of: date) -> tuple[Partition, Partition]:
    day = pl.col("as_of_date") == as_of.isoformat()
    legal = inputs.domains.lei_required.to_list()
    cpty = _sorted(
        counterparty_faults(rng, inputs.counterparties.filter(day), as_of, inputs.rates[0], legal), "counterparty"
    )
    cpty_reasons = counterparty_reasons(cpty, as_of, inputs.domains)
    accepted = accepted_ids(cpty, cpty_reasons)
    expo = _sorted(exposure_faults(rng, inputs.exposures.filter(day), as_of, inputs.rates[1], accepted), "exposure")
    expo_reasons = exposure_reasons(expo, as_of, inputs.domains, accepted)
    return _partition("counterparty", as_of, cpty, cpty_reasons), _partition("exposure", as_of, expo, expo_reasons)


def _sorted(frame: pl.DataFrame, feed: str) -> pl.DataFrame:
    return frame.sort(IDS[feed], maintain_order=True)


def _partition(feed: str, as_of: date, frame: pl.DataFrame, reasons: pl.Series) -> Partition:
    expected = (
        pl.DataFrame({REASON: reasons})
        .with_row_index("src_row", offset=1)
        .with_columns(pl.col("src_row").cast(pl.Int64))
        .filter(pl.col(REASON).is_not_null())
    )
    return Partition(feed, as_of, frame.drop(REASON), expected, frame[REASON])
