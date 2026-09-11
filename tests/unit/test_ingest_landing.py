import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from srdwh.config import load_settings
from srdwh.contracts.landing import DATA_FILE, MANIFEST
from srdwh.files import parquet
from srdwh.generate.landing import write_landing
from srdwh.ingest.landing import StructuralError, partitions, read_delivery

SETTINGS = Path(__file__).resolve().parents[2] / "srdwh.toml"
FIRST = "counterparty/as_of_date=2025-10-31"


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory, ref_dir: Path) -> Path:
    data_dir = tmp_path_factory.mktemp("generated")
    write_landing(load_settings(SETTINGS).profile("ci"), ref_dir, data_dir)
    return data_dir / "landing"


@pytest.fixture
def landing(generated: Path, tmp_path: Path) -> Path:
    return Path(shutil.copytree(generated, tmp_path / "landing"))


def edit_manifest(folder: Path, **changes: object) -> None:
    manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8")) | changes
    (folder / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")


def replace_data(folder: Path, data: bytes, rows: int) -> None:
    (folder / DATA_FILE).write_bytes(data)
    edit_manifest(folder, sha256=hashlib.sha256(data).hexdigest(), rows=rows)


def test_partitions_in_as_of_then_feed_order(landing: Path) -> None:
    found = partitions(landing)
    assert [(p.as_of.isoformat(), p.feed) for p in found][:3] == [
        ("2025-10-31", "counterparty"),
        ("2025-10-31", "exposure"),
        ("2025-11-30", "counterparty"),
    ]
    assert found[0].file_path == f"{FIRST}/{DATA_FILE}"
    assert all(p.ready for p in found)


def test_read_delivery_matches_manifest(landing: Path) -> None:
    delivery = read_delivery(partitions(landing)[0])
    manifest = json.loads((landing / FIRST / MANIFEST).read_text(encoding="utf-8"))
    assert (delivery.frame.height, delivery.sha256) == (manifest["rows"], manifest["sha256"])


def test_partition_without_manifest_not_ready(landing: Path) -> None:
    (landing / FIRST / MANIFEST).unlink()
    assert not partitions(landing)[0].ready


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        (lambda f: edit_manifest(f, sha256="0" * 64), "sha256 differs"),
        (lambda f: edit_manifest(f, rows=1), "manifest announces 1"),
        (lambda f: edit_manifest(f, contract_version="2"), "manifest contract_version do not match"),
        (lambda f: edit_manifest(f, feed="exposure"), "manifest feed do not match"),
        (lambda f: edit_manifest(f, extra=1), "manifest keys differ"),
        (lambda f: (f / MANIFEST).write_text("{", encoding="utf-8"), "unreadable manifest"),
        (lambda f: replace_data(f, b"not parquet", 0), "unreadable Parquet"),
        (lambda f: (f / DATA_FILE).unlink(), "unreadable data file"),
        (
            lambda f: replace_data(f, parquet(pl.read_parquet(f / DATA_FILE).rename({"lei": "lei_code"})), 501),
            "column_in",
        ),
    ],
)
def test_structural_errors(landing: Path, tamper: Callable[[Path], object], message: str) -> None:
    tamper(landing / FIRST)
    with pytest.raises(StructuralError, match=message):
        read_delivery(partitions(landing)[0])


@pytest.mark.parametrize(
    ("folder", "message"),
    [("trades/as_of_date=2025-10-31", "unknown feed"), ("exposure/as_of_date=2025-13-31", "invalid partition date")],
)
def test_unexpected_folders_fail(landing: Path, folder: str, message: str) -> None:
    (landing / folder).mkdir(parents=True)
    with pytest.raises(StructuralError, match=message):
        partitions(landing)
