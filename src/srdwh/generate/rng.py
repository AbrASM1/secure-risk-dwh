from types import MappingProxyType

import numpy as np

STREAMS = MappingProxyType({"counterparty": 1, "exposure": 2, "fault": 3})


def stream(seed: int, name: str) -> np.random.Generator:
    return np.random.default_rng([seed, STREAMS[name]])


def categorical(uniform: np.ndarray, cumulative: np.ndarray) -> np.ndarray:
    return np.sum(cumulative <= uniform[:, np.newaxis], axis=-1)


def cumulative(probabilities: np.ndarray) -> np.ndarray:
    totals = np.cumsum(probabilities, axis=-1)
    return totals / totals[..., -1:]
