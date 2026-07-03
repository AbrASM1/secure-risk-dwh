import tomllib
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

SETTINGS = Path(__file__).resolve().parents[2] / "srdwh.toml"
GOLDEN_AS_OF = date(2000, 1, 31)
LAST_CALENDAR_DAY = date(2040, 12, 31)


def settings() -> dict[str, Any]:
    return tomllib.loads(SETTINGS.read_text(encoding="utf-8"))


def month_end_after(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months + 1
    return date(index // 12, index % 12 + 1, 1) - timedelta(days=1)


def test_profiles_match_spec() -> None:
    sizes = {
        name: (profile["counterparties"], profile["exposures"], profile["as_of_count"])
        for name, profile in settings()["profiles"].items()
    }
    assert sizes == {"dev": (5_000, 50_000, 12), "ci": (500, 2_000, 3)}


def test_reject_threshold_matches_spec() -> None:
    assert settings()["reject_threshold"] == pytest.approx(0.05)


@pytest.mark.parametrize("name", ["dev", "ci"])
def test_as_of_range_avoids_golden_set_and_fits_calendar(name: str) -> None:
    profile = settings()["profiles"][name]
    first: date = profile["first_as_of"]
    assert first == month_end_after(first, 0)
    assert first > GOLDEN_AS_OF
    assert month_end_after(first, profile["as_of_count"] - 1) <= LAST_CALENDAR_DAY
