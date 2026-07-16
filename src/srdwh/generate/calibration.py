from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from srdwh.contracts.reference import read_reference
from srdwh.contracts.validation import ContractError


@dataclass(frozen=True)
class Calibration:
    values: pl.DataFrame

    @classmethod
    def read(cls, ref_dir: Path) -> "Calibration":
        frame = read_reference(ref_dir, "calibration")
        return cls(frame.select("parameter", "key", pl.col("value").cast(pl.Float64)))

    def keyed(self, parameter: str) -> pl.DataFrame:
        rows = self.values.filter(pl.col("parameter") == parameter).select("key", "value")
        if rows.is_empty():
            raise ContractError(f"calibration: missing parameter {parameter}")
        return rows

    def scalar(self, parameter: str) -> float:
        rows = self.keyed(parameter)
        if rows["key"].to_list() != [""]:
            raise ContractError(f"calibration: {parameter} is not a scalar")
        return float(rows["value"].item())

    def aligned(self, parameter: str, keys: Sequence[str]) -> np.ndarray:
        found = pl.DataFrame({"key": list(keys)}, schema={"key": pl.Utf8}).join(
            self.keyed(parameter), on="key", how="left", maintain_order="left"
        )
        missing = found.filter(pl.col("value").is_null())["key"].to_list()
        if missing:
            raise ContractError(f"calibration: {parameter} lacks {', '.join(missing)}")
        return found["value"].to_numpy()
