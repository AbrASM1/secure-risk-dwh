from datetime import date
from pathlib import Path

DATA_FILE = "part-0.parquet"
MANIFEST = "manifest.json"
EXPECTED = "expected.parquet"
MANIFEST_KEYS = frozenset({"feed", "as_of_date", "rows", "sha256", "seed", "profile", "contract_version"})
PARTITION_PREFIX = "as_of_date="


def partition_folder(feed: str, as_of: date) -> Path:
    return Path(feed) / f"{PARTITION_PREFIX}{as_of.isoformat()}"
