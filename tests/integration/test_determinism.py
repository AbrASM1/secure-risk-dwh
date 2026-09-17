import hashlib
from collections.abc import Callable
from pathlib import Path

import oracledb
import pytest

from srdwh.config import Profile
from tests.integration.db import rows
from tests.integration.pipeline import landing, retire, run

pytestmark = pytest.mark.db
TOTALS = """
    SELECT TO_CHAR(as_of_date, 'YYYY-MM-DD'), count(*), TO_CHAR(sum(ead)), TO_CHAR(sum(e_star)), TO_CHAR(sum(rwa))
    FROM srdwh_owner.gld_fact_rwa WHERE as_of_date BETWEEN :first AND :last GROUP BY as_of_date ORDER BY 1"""


def digests(data_dir: Path) -> dict[str, str]:
    files = sorted((data_dir / "landing").rglob("*.parquet"))
    return {str(path.relative_to(data_dir)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def test_gold_totals_identical(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    owner_connection: oracledb.Connection,
    pipeline_profile: Callable[[int], Profile],
) -> None:
    profile = pipeline_profile(2)
    window = {"first": profile.first_as_of, "last": profile.as_of_dates[-1]}
    first, second = landing(tmp_path / "first", profile), landing(tmp_path / "second", profile)
    assert digests(first) == digests(second)
    assert run(first, capsys, monkeypatch)[0] == 0
    totals = rows(owner_connection, TOTALS, **window)
    retire(owner_connection, profile)
    assert run(second, capsys, monkeypatch)[0] == 0
    assert len(totals) == 2
    assert rows(owner_connection, TOTALS, **window) == totals
