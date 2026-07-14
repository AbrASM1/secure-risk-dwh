from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from srdwh.config import ConfigError, Credentials, credentials, load_settings

SETTINGS = Path(__file__).resolve().parents[2] / "srdwh.toml"
MARKER = "Zq7MarkerValue42abcdefgh"


def settings_with(tmp_path: Path, old: str, new: str) -> Path:
    text = SETTINGS.read_text(encoding="utf-8")
    assert old in text
    path = tmp_path / "srdwh.toml"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


def test_settings_load() -> None:
    settings = load_settings(SETTINGS)
    assert settings.batch_size == 10_000
    assert settings.reject_threshold == Decimal("0.05")
    assert settings.profile("ci").first_as_of == date(2025, 10, 31)
    assert [p.name for p in settings.profiles] == ["ci", "dev"]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("batch_size = 10000", "batch_size = 10000\nbatch_sise = 1"),
        ("seed = 42", "seed = 42\nseeds = 1"),
        ("seed = 42", "seed = 42\npassword = 'x'"),
    ],
)
def test_unknown_key_fails(tmp_path: Path, old: str, new: str) -> None:
    with pytest.raises(ConfigError, match="unknown key"):
        load_settings(settings_with(tmp_path, old, new))


def test_missing_key_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="missing key"):
        load_settings(settings_with(tmp_path, "exposures = 2000\n", ""))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("batch_size = 10000", "batch_size = 0"),
        ("batch_size = 10000", "batch_size = true"),
        ("batch_size = 10000", "batch_size = 1.5"),
        ("reject_threshold = 0.05", "reject_threshold = 1.5"),
        ("reject_threshold = 0.05", "reject_threshold = -0.01"),
        ("reject_threshold = 0.05", "reject_threshold = '0.05'"),
        ("seed = 42", "seed = -1"),
        ("counterparties = 500", "counterparties = 0"),
        ("exposures = 2000", "exposures = 0"),
        ("as_of_count = 3", "as_of_count = 0"),
        ("first_as_of = 2025-10-31", "first_as_of = 2025-10-30"),
        ("first_as_of = 2025-10-31", "first_as_of = 2000-01-31"),
        ("first_as_of = 2025-10-31", "first_as_of = 2040-11-30"),
        ("first_as_of = 2025-10-31", "first_as_of = '2025-10-31'"),
        ("first_as_of = 2025-10-31", "first_as_of = 2025-10-31T00:00:00"),
        ("[profiles.ci]", "[profiles.ci]\n[profiles.ci.extra]"),
    ],
)
def test_out_of_domain_value_fails(tmp_path: Path, old: str, new: str) -> None:
    with pytest.raises(ConfigError):
        load_settings(settings_with(tmp_path, old, new))


def test_last_as_of_on_calendar_bound_passes(tmp_path: Path) -> None:
    path = settings_with(tmp_path, "first_as_of = 2025-10-31", "first_as_of = 2040-10-31")
    assert load_settings(path).profile("ci").first_as_of == date(2040, 10, 31)


def test_unreadable_settings_fail(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "absent.toml")
    with pytest.raises(ConfigError):
        load_settings(settings_with(tmp_path, "batch_size = 10000", "batch_size = "))


def test_unknown_profile_fails() -> None:
    with pytest.raises(ConfigError, match="unknown profile"):
        load_settings(SETTINGS).profile("prod")


def test_passwords_from_env_only() -> None:
    environ = {"SRDWH_DSN": "localhost:1521/FREEPDB1", "SRDWH_ETL_PASSWORD": MARKER}
    found = credentials("SRDWH_ETL", environ)
    assert found == Credentials(user="SRDWH_ETL", dsn="localhost:1521/FREEPDB1", password=MARKER)
    assert MARKER not in repr(found)
    assert "password" not in {field.lower() for field in load_settings(SETTINGS).__dataclass_fields__}


@pytest.mark.parametrize(
    "environ",
    [
        {"SRDWH_ETL_PASSWORD": MARKER},
        {"SRDWH_DSN": "localhost:1521/FREEPDB1"},
        {"SRDWH_DSN": "x", "SRDWH_ETL_PASSWORD": ""},
    ],
)
def test_missing_variable_fails(environ: dict[str, str]) -> None:
    with pytest.raises(ConfigError, match="environment variable") as error:
        credentials("SRDWH_ETL", environ)
    assert MARKER not in str(error.value)


def test_unknown_account_fails() -> None:
    with pytest.raises(ConfigError, match="unknown account"):
        credentials("SYSTEM", {"SRDWH_DSN": "x", "SYSTEM_PASSWORD": MARKER})


@pytest.mark.parametrize("profiles", ["{}", "1"])
def test_profiles_must_be_a_non_empty_table(tmp_path: Path, profiles: str) -> None:
    path = tmp_path / "srdwh.toml"
    path.write_text(f"batch_size = 1\nreject_threshold = 0.05\nprofiles = {profiles}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="non-empty table"):
        load_settings(path)
