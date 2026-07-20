from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

from srdwh.config import Profile
from srdwh.contracts.feeds import EXPOSURE_COLUMNS
from srdwh.generate.calibration import Calibration
from srdwh.generate.rng import categorical, cumulative, stream

CURRENCY = "EUR"
NO_COLLATERAL = -1


@dataclass(frozen=True)
class ExposureModel:
    products: np.ndarray
    product_cumulative: np.ndarray
    segments: np.ndarray
    amount_median: np.ndarray
    amount_sigma: float
    line_drawn_share_max: float
    collateral_share: float
    collateral_types: np.ndarray
    collateral_cumulative: np.ndarray
    collateral_ratio: tuple[float, float]
    replacement: float
    drift: float


@dataclass(frozen=True)
class _Book:
    exposure_no: np.ndarray
    cpty: np.ndarray
    product: np.ndarray
    drawn: np.ndarray
    undrawn: np.ndarray
    collateral: np.ndarray
    collateral_type: np.ndarray


def exposure_model(calibration: Calibration, segments: np.ndarray) -> ExposureModel:
    products = calibration.keyed("product_share")
    collateral_types = calibration.keyed("collateral_type_share")
    return ExposureModel(
        products=products["key"].to_numpy(),
        product_cumulative=cumulative(products["value"].to_numpy()),
        segments=segments,
        amount_median=calibration.aligned("amount_median", segments.tolist()),
        amount_sigma=calibration.scalar("amount_sigma"),
        line_drawn_share_max=calibration.scalar("line_drawn_share_max"),
        collateral_share=calibration.scalar("collateral_share"),
        collateral_types=collateral_types["key"].to_numpy(),
        collateral_cumulative=cumulative(collateral_types["value"].to_numpy()),
        collateral_ratio=(calibration.scalar("collateral_ratio_min"), calibration.scalar("collateral_ratio_max")),
        replacement=calibration.scalar("exposure_replacement_monthly"),
        drift=calibration.scalar("amount_drift_max"),
    )


def exposures(profile: Profile, model: ExposureModel, cpty_ids: pl.Series, cpty_segments: pl.Series) -> pl.DataFrame:
    rng = stream(profile.seed, "exposure")
    medians = (
        pl.DataFrame({"segment": cpty_segments})
        .join(pl.DataFrame({"segment": model.segments, "median": model.amount_median}), on="segment", how="left")
        .get_column("median")
        .to_numpy()
    )
    book = _new(rng, model, medians, np.arange(1, profile.exposures + 1))
    frames = []
    for month, as_of in enumerate(profile.as_of_dates):
        book = _next_month(rng, model, medians, book) if month else book
        frames.append(_feed(model, book, cpty_ids, as_of))
    return pl.concat(frames)


def _new(rng: np.random.Generator, model: ExposureModel, medians: np.ndarray, exposure_no: np.ndarray) -> _Book:
    size = int(exposure_no.shape[0])
    cpty = rng.integers(medians.shape[0], size=size)
    product = categorical(rng.random(size), model.product_cumulative)
    amount = np.rint(medians[cpty] * np.exp(model.amount_sigma * rng.standard_normal(size)) * 100).astype(np.int64)
    codes = model.products[product]
    line_share = rng.uniform(0, model.line_drawn_share_max, size)
    drawn_share = np.where(codes == "LOAN", 1.0, np.where(codes == "UNDRAWN_LINE", line_share, 0.0))
    drawn = np.rint(amount * drawn_share).astype(np.int64)
    secured = rng.random(size) < model.collateral_share
    collateral_type = np.where(secured, categorical(rng.random(size), model.collateral_cumulative), NO_COLLATERAL)
    ratio = rng.uniform(*model.collateral_ratio, size)
    collateral = np.where(secured, np.rint(amount * ratio), 0).astype(np.int64)
    return _Book(exposure_no, cpty, product, drawn, amount - drawn, collateral, collateral_type)


def _next_month(rng: np.random.Generator, model: ExposureModel, medians: np.ndarray, book: _Book) -> _Book:
    size = int(book.exposure_no.shape[0])
    replaced = rng.random(size) < model.replacement
    factor = 1 + rng.uniform(-model.drift, model.drift, size)
    numbers = np.where(replaced, int(book.exposure_no.max()) + np.cumsum(replaced), book.exposure_no)
    fresh = _new(rng, model, medians, numbers)
    return _Book(
        exposure_no=numbers,
        cpty=np.where(replaced, fresh.cpty, book.cpty),
        product=np.where(replaced, fresh.product, book.product),
        drawn=np.where(replaced, fresh.drawn, _scaled(book.drawn, factor)),
        undrawn=np.where(replaced, fresh.undrawn, _scaled(book.undrawn, factor)),
        collateral=np.where(replaced, fresh.collateral, _scaled(book.collateral, factor)),
        collateral_type=np.where(replaced, fresh.collateral_type, book.collateral_type),
    )


def _scaled(cents: np.ndarray, factor: np.ndarray) -> np.ndarray:
    scaled: np.ndarray = np.rint(cents * factor).astype(np.int64)
    return scaled


def _amount(column: str) -> pl.Expr:
    return pl.format("{}.{}", pl.col(column) // 100, (pl.col(column) % 100).cast(pl.Utf8).str.zfill(2))


def _feed(model: ExposureModel, book: _Book, cpty_ids: pl.Series, as_of: date) -> pl.DataFrame:
    secured = book.collateral_type != NO_COLLATERAL
    return (
        pl.DataFrame(
            {
                "exposure_no": book.exposure_no,
                "cpty_id": cpty_ids.gather(book.cpty),
                "product_code": model.products[book.product],
                "drawn": book.drawn,
                "undrawn": book.undrawn,
                "collateral": book.collateral,
                "collateral_type": np.where(secured, model.collateral_types[np.maximum(book.collateral_type, 0)], ""),
                "secured": secured,
            }
        )
        .select(
            pl.format("EX{}", pl.col("exposure_no").cast(pl.Utf8).str.zfill(10)).alias("exposure_id"),
            "cpty_id",
            "product_code",
            _amount("drawn").alias("drawn_amt"),
            _amount("undrawn").alias("undrawn_amt"),
            pl.when("secured").then(_amount("collateral")).otherwise(pl.lit("")).alias("collateral_amt"),
            "collateral_type",
            pl.lit(CURRENCY).alias("currency"),
            pl.lit(as_of.isoformat()).alias("as_of_date"),
        )
        .select(EXPOSURE_COLUMNS)
    )
