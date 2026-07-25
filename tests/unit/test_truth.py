from datetime import date
from pathlib import Path

import polars as pl
import pytest

from srdwh.contracts.feeds import COUNTERPARTY_COLUMNS, EXPOSURE_COLUMNS
from srdwh.generate.lei import with_check_digits
from srdwh.generate.truth import Domains, accepted_ids, counterparty_reasons, exposure_reasons

AS_OF = date(2025, 1, 31)
LEI = pl.select(with_check_digits(pl.lit("SRDWHTEST000000001"))).item()
COUNTERPARTY = {
    "cpty_id": "CP00000001",
    "cpty_name": "Atlas Foods SA",
    "lei": LEI,
    "segment_code": "CORPORATE",
    "country": "FR",
    "rating": "BBB",
    "default_flag": "N",
    "as_of_date": "2025-01-31",
}
EXPOSURE = {
    "exposure_id": "EX0000000001",
    "cpty_id": "CP00000001",
    "product_code": "LOAN",
    "drawn_amt": "1000.00",
    "undrawn_amt": "0.00",
    "collateral_amt": "",
    "collateral_type": "",
    "currency": "EUR",
    "as_of_date": "2025-01-31",
}


@pytest.fixture(scope="module")
def domains(ref_dir: Path) -> Domains:
    return Domains.read(ref_dir)


def counterparty_frame(*changes: dict[str, str]) -> pl.DataFrame:
    return pl.DataFrame(
        [COUNTERPARTY | change for change in changes], schema=dict.fromkeys(COUNTERPARTY_COLUMNS, pl.Utf8)
    )


def exposure_frame(*changes: dict[str, str]) -> pl.DataFrame:
    return pl.DataFrame([EXPOSURE | change for change in changes], schema=dict.fromkeys(EXPOSURE_COLUMNS, pl.Utf8))


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({}, None),
        ({"cpty_id": "C" * 20}, None),
        ({"cpty_id": "C" * 21}, "C01"),
        ({"cpty_id": "   "}, "C01"),
        ({"cpty_name": "x" * 200}, None),
        ({"cpty_name": "x" * 201}, "C01"),
        ({"as_of_date": "2026-02-30"}, "C02"),
        ({"as_of_date": "2025-1-31"}, "C02"),
        ({"as_of_date": "2024-12-31"}, "C02"),
        ({"as_of_date": " 2025-01-31 "}, None),
        ({"segment_code": "corporate"}, "C03"),
        ({"segment_code": " CORPORATE "}, None),
        ({"segment_code": ""}, "C03"),
        ({"rating": "NR"}, None),
        ({"rating": "C"}, "C04"),
        ({"rating": "aaa"}, "C04"),
        ({"default_flag": "y"}, "C05"),
        ({"default_flag": ""}, "C05"),
        ({"lei": LEI.lower()}, "C06"),
        ({"lei": ""}, "C06"),
        ({"lei": LEI[:-1] + str((int(LEI[-1]) + 1) % 10)}, "C06"),
        ({"segment_code": "SME", "lei": ""}, None),
        ({"segment_code": "RETAIL", "lei": LEI}, None),
        ({"country": "fr"}, "C07"),
        ({"country": "FRA"}, "C07"),
        ({"segment_code": "corporate", "country": "fr"}, "C03"),
    ],
)
def test_counterparty_rule_boundaries(domains: Domains, change: dict[str, str], expected: str | None) -> None:
    assert counterparty_reasons(counterparty_frame(change), AS_OF, domains).to_list() == [expected]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (({}, {}), ["C08", "C08"]),
        (({}, {"cpty_id": "CP00000001 "}), ["C08", "C08"]),
        (({}, {"rating": "C"}), ["C08", "C04"]),
        (({}, {"cpty_id": "CP00000002"}), [None, None]),
    ],
)
def test_counterparty_duplicates(
    domains: Domains, changes: tuple[dict[str, str], ...], expected: list[str | None]
) -> None:
    assert counterparty_reasons(counterparty_frame(*changes), AS_OF, domains).to_list() == expected


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({}, None),
        ({"exposure_id": "E" * 30}, None),
        ({"exposure_id": "E" * 31}, "R01"),
        ({"cpty_id": ""}, "R01"),
        ({"drawn_amt": "1" * 16}, None),
        ({"drawn_amt": "1" * 17}, "R02"),
        ({"drawn_amt": "1e3"}, "R02"),
        ({"drawn_amt": "1,50"}, "R02"),
        ({"drawn_amt": "1.505"}, "R02"),
        ({"collateral_amt": "abc", "collateral_type": "CASH"}, "R02"),
        ({"drawn_amt": "-0.01"}, "R03"),
        ({"drawn_amt": "0"}, None),
        ({"drawn_amt": "-0"}, None),
        ({"product_code": "loan"}, "R04"),
        ({"as_of_date": "2025-1-31"}, "R05"),
        ({"cpty_id": "CP99999999"}, "R07"),
        ({"cpty_id": "CP99999999", "drawn_amt": "1e3"}, "R02"),
        ({"collateral_amt": "0.01"}, "R08"),
        ({"collateral_amt": "0.00"}, None),
        ({"collateral_type": "cash"}, "R09"),
        ({"collateral_amt": "100.00", "collateral_type": "CASH"}, None),
        ({"undrawn_amt": "0.01"}, "R10"),
        ({"product_code": "GUARANTEE", "drawn_amt": "0.01"}, "R10"),
        ({"product_code": "UNDRAWN_LINE", "drawn_amt": "10.00", "undrawn_amt": "5.00"}, None),
        ({"currency": "eur"}, "R11"),
        ({"currency": "USD"}, "R11"),
    ],
)
def test_exposure_rule_boundaries(domains: Domains, change: dict[str, str], expected: str | None) -> None:
    accepted = pl.Series(["CP00000001"])
    assert exposure_reasons(exposure_frame(change), AS_OF, domains, accepted).to_list() == [expected]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (({}, {}), ["R06", "R06"]),
        (({}, {"exposure_id": "EX0000000001 "}), ["R06", "R06"]),
        (({}, {"drawn_amt": "1e3"}), ["R06", "R02"]),
    ],
)
def test_exposure_duplicates(domains: Domains, changes: tuple[dict[str, str], ...], expected: list[str | None]) -> None:
    accepted = pl.Series(["CP00000001"])
    assert exposure_reasons(exposure_frame(*changes), AS_OF, domains, accepted).to_list() == expected


def test_rejected_counterparty_cascades_to_r07(domains: Domains) -> None:
    counterparties = counterparty_frame({}, {"cpty_id": "CP00000002", "rating": "C"}, {"cpty_id": "CP00000003 "})
    accepted = accepted_ids(counterparties, counterparty_reasons(counterparties, AS_OF, domains))
    assert accepted.to_list() == ["CP00000001", "CP00000003"]
    exposures = exposure_frame(
        {}, {"exposure_id": "EX2", "cpty_id": "CP00000002"}, {"exposure_id": "EX3", "cpty_id": "CP00000003"}
    )
    assert exposure_reasons(exposures, AS_OF, domains, accepted).to_list() == [None, "R07", None]
