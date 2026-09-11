import hashlib
import json
from pathlib import Path

from srdwh.config import Profile
from srdwh.contracts.feeds import CONTRACT_VERSION
from srdwh.contracts.landing import DATA_FILE, EXPECTED, MANIFEST, partition_folder
from srdwh.files import parquet, write_atomic
from srdwh.generate.simulate import Partition, simulate


def write_landing(profile: Profile, ref_dir: Path, data_dir: Path) -> None:
    for partition in simulate(profile, ref_dir):
        write_partition(partition, data_dir, profile)


def write_partition(partition: Partition, data_dir: Path, profile: Profile) -> Path:
    folder = partition_folder(partition.feed, partition.as_of)
    landing = data_dir / "landing" / folder
    (landing / MANIFEST).unlink(missing_ok=True)
    data = parquet(partition.rows)
    write_atomic(data_dir / "ground_truth" / folder / EXPECTED, parquet(partition.expected))
    write_atomic(landing / DATA_FILE, data)
    write_atomic(landing / MANIFEST, _manifest(partition, data, profile))
    return landing


def _manifest(partition: Partition, data: bytes, profile: Profile) -> bytes:
    content = {
        "feed": partition.feed,
        "as_of_date": partition.as_of.isoformat(),
        "rows": partition.rows.height,
        "sha256": hashlib.sha256(data).hexdigest(),
        "seed": profile.seed,
        "profile": profile.name,
        "contract_version": CONTRACT_VERSION,
    }
    return (json.dumps(content, indent=2, sort_keys=True) + "\n").encode("utf-8")
