from math import sqrt

import numpy as np
import polars as pl


def mean(series: pl.Series) -> float:
    return float(np.mean(series.cast(pl.Float64).to_numpy()))


def within(observed: float, expected: float, size: int) -> bool:
    return abs(observed - expected) <= 4 * sqrt(expected * (1 - expected) / size) + 1e-12
