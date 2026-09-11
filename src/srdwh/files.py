import io
import os
from pathlib import Path

import polars as pl

ZSTD_LEVEL = 3
ROW_GROUP_SIZE = 100_000


def parquet(frame: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.write_parquet(buffer, compression="zstd", compression_level=ZSTD_LEVEL, row_group_size=ROW_GROUP_SIZE)
    return buffer.getvalue()


def write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
