import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

GOLDEN_AS_OF = date(2000, 1, 31)
LAST_CALENDAR_DAY = date(2040, 12, 31)
SETTINGS_KEYS = frozenset({"batch_size", "reject_threshold", "profiles"})
PROFILE_KEYS = frozenset({"seed", "first_as_of", "as_of_count", "counterparties", "exposures"})
ACCOUNTS = frozenset(
    {
        "SRDWH_OWNER",
        "SRDWH_ETL",
        "ANALYST_CORP",
        "ANALYST_RETAIL",
        "RISK_MANAGER",
        "AUDITOR",
        "PROBE_NOPROFILE",
    }
)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Profile:
    name: str
    seed: int
    first_as_of: date
    as_of_count: int
    counterparties: int
    exposures: int

    @property
    def as_of_dates(self) -> tuple[date, ...]:
        return tuple(month_end(self.first_as_of, months) for months in range(self.as_of_count))


@dataclass(frozen=True)
class Settings:
    batch_size: int
    reject_threshold: Decimal
    profiles: tuple[Profile, ...]

    def profile(self, name: str) -> Profile:
        found = [p for p in self.profiles if p.name == name]
        if not found:
            raise ConfigError(f"unknown profile {name!r}")
        return found[0]


@dataclass(frozen=True)
class Credentials:
    user: str
    dsn: str
    password: str = field(repr=False)


def month_end(day: date, months: int) -> date:
    index = day.year * 12 + day.month + months
    return date(index // 12, index % 12 + 1, 1) - timedelta(days=1)


def load_settings(path: Path) -> Settings:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"{path.name}: {error}") from None
    _check_keys(path.name, raw, SETTINGS_KEYS)
    profiles = _table(path.name, raw, "profiles")
    return Settings(
        batch_size=_integer(path.name, raw, "batch_size", 1),
        reject_threshold=_rate(path.name, raw, "reject_threshold"),
        profiles=tuple(_profile(name, _table("profiles", profiles, name)) for name in sorted(profiles)),
    )


def credentials(account: str, environ: Mapping[str, str] = os.environ) -> Credentials:
    if account not in ACCOUNTS:
        raise ConfigError(f"unknown account {account!r}")
    return Credentials(
        user=account,
        dsn=_variable(environ, "SRDWH_DSN"),
        password=_variable(environ, f"{account}_PASSWORD"),
    )


def _profile(name: str, table: dict[str, Any]) -> Profile:
    where = f"profiles.{name}"
    _check_keys(where, table, PROFILE_KEYS)
    profile = Profile(
        name=name,
        seed=_integer(where, table, "seed", 0),
        first_as_of=_date(where, table, "first_as_of"),
        as_of_count=_integer(where, table, "as_of_count", 1),
        counterparties=_integer(where, table, "counterparties", 1),
        exposures=_integer(where, table, "exposures", 1),
    )
    _check_calendar(where, profile)
    return profile


def _check_calendar(where: str, profile: Profile) -> None:
    first = profile.first_as_of
    if first != month_end(first, 0) or first <= GOLDEN_AS_OF:
        raise ConfigError(f"{where}.first_as_of must be a month end after {GOLDEN_AS_OF}")
    if month_end(first, profile.as_of_count - 1) > LAST_CALENDAR_DAY:
        raise ConfigError(f"{where}: last as_of after {LAST_CALENDAR_DAY}")


def _check_keys(where: str, table: dict[str, Any], expected: frozenset[str]) -> None:
    unknown, missing = sorted(set(table) - expected), sorted(expected - set(table))
    if unknown:
        raise ConfigError(f"{where}: unknown key {', '.join(unknown)}")
    if missing:
        raise ConfigError(f"{where}: missing key {', '.join(missing)}")


def _table(where: str, table: dict[str, Any], key: str) -> dict[str, Any]:
    value = table[key]
    if not isinstance(value, dict) or not value:
        raise ConfigError(f"{where}.{key} must be a non-empty table")
    return value


def _integer(where: str, table: dict[str, Any], key: str, minimum: int) -> int:
    value = table[key]
    if type(value) is not int or value < minimum:
        raise ConfigError(f"{where}.{key} must be an integer >= {minimum}")
    return value


def _rate(where: str, table: dict[str, Any], key: str) -> Decimal:
    value = table[key]
    if type(value) not in (int, Decimal) or not 0 <= value <= 1:
        raise ConfigError(f"{where}.{key} must be a number in [0, 1]")
    return Decimal(value)


def _date(where: str, table: dict[str, Any], key: str) -> date:
    value = table[key]
    if type(value) is not date:
        raise ConfigError(f"{where}.{key} must be a date")
    return value


def _variable(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "")
    if not value:
        raise ConfigError(f"environment variable {name} is missing or empty")
    return value
