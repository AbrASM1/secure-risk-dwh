import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from srdwh.contracts.feeds import CONTRACT_VERSION, FEEDS, validate_feed
from srdwh.contracts.landing import DATA_FILE, MANIFEST, MANIFEST_KEYS, PARTITION_PREFIX
from srdwh.contracts.validation import ContractError

FEED_ORDER = ("counterparty", "exposure")


class StructuralError(ValueError):
    pass


@dataclass(frozen=True)
class Partition:
    feed: str
    as_of: date
    folder: Path
    file_path: str

    @property
    def ready(self) -> bool:
        return (self.folder / MANIFEST).is_file()


@dataclass(frozen=True)
class Delivery:
    partition: Partition
    frame: pl.DataFrame
    sha256: str


def partitions(landing: Path) -> list[Partition]:
    found = [_partition(landing, folder) for folder in landing.glob(f"*/{PARTITION_PREFIX}*") if folder.is_dir()]
    return sorted(found, key=lambda p: (p.as_of, FEED_ORDER.index(p.feed)))


def read_delivery(partition: Partition) -> Delivery:
    manifest = _manifest(partition)
    data = _data(partition)
    sha256 = hashlib.sha256(data).hexdigest()
    if sha256 != manifest["sha256"]:
        raise StructuralError(f"{partition.file_path}: sha256 differs from the manifest")
    frame = _frame(partition, data)
    if frame.height != manifest["rows"]:
        raise StructuralError(f"{partition.file_path}: {frame.height} rows, manifest announces {manifest['rows']}")
    return Delivery(partition, frame, sha256)


def _partition(landing: Path, folder: Path) -> Partition:
    where = folder.relative_to(landing)
    if folder.parent.name not in FEEDS:
        raise StructuralError(f"{where}: unknown feed")
    try:
        as_of = date.fromisoformat(folder.name.removeprefix(PARTITION_PREFIX))
    except ValueError:
        raise StructuralError(f"{where}: invalid partition date") from None
    return Partition(folder.parent.name, as_of, folder, str(where / DATA_FILE))


def _manifest(partition: Partition) -> dict[str, object]:
    try:
        content = json.loads((partition.folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise StructuralError(f"{partition.file_path}: unreadable manifest") from None
    if not isinstance(content, dict) or set(content) != MANIFEST_KEYS:
        raise StructuralError(f"{partition.file_path}: manifest keys differ from the contract")
    expected = {"feed": partition.feed, "as_of_date": partition.as_of.isoformat(), "contract_version": CONTRACT_VERSION}
    mismatched = sorted(key for key, value in expected.items() if content[key] != value)
    if mismatched:
        raise StructuralError(f"{partition.file_path}: manifest {', '.join(mismatched)} do not match")
    return content


def _data(partition: Partition) -> bytes:
    try:
        return (partition.folder / DATA_FILE).read_bytes()
    except OSError:
        raise StructuralError(f"{partition.file_path}: unreadable data file") from None


def _frame(partition: Partition, data: bytes) -> pl.DataFrame:
    try:
        return validate_feed(partition.feed, pl.read_parquet(io.BytesIO(data)))
    except ContractError as error:
        raise StructuralError(f"{partition.file_path}: {error}") from None
    except pl.exceptions.PolarsError:
        raise StructuralError(f"{partition.file_path}: unreadable Parquet") from None
