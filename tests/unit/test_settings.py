from decimal import Decimal
from pathlib import Path

from srdwh.config import load_settings

SETTINGS = Path(__file__).resolve().parents[2] / "srdwh.toml"


def test_profiles_match_spec() -> None:
    sizes = {p.name: (p.counterparties, p.exposures, p.as_of_count) for p in load_settings(SETTINGS).profiles}
    assert sizes == {"dev": (5_000, 50_000, 12), "ci": (500, 2_000, 3)}


def test_reject_threshold_matches_spec() -> None:
    assert load_settings(SETTINGS).reject_threshold == Decimal("0.05")
