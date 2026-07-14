import re
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from srdwh.contracts.reference import REFERENCES, read_reference
from srdwh.contracts.validation import ContractError

REPO = Path(__file__).resolve().parents[2]
REF = REPO / "db" / "ref"
SPEC = (REPO / "docs" / "SPEC.md").read_text(encoding="utf-8")
S_AND_P = {
    "AAA": "0.0000",
    "AA": "0.0002",
    "A": "0.0005",
    "BBB": "0.0014",
    "BB": "0.0056",
    "B": "0.0293",
    "CCC": "0.2612",
}
SHARES = {
    "segment_share": "segment",
    "product_share": "product",
    "country_share": "country",
    "collateral_type_share": "collateral_type",
}


def column(name: str, field: str) -> list[str]:
    return read_reference(REF, name)[field].to_list()


def calibration(parameter: str) -> dict[str, str]:
    frame = read_reference(REF, "calibration").filter(pl.col("parameter") == parameter)
    return dict(zip(frame["key"], frame["value"], strict=True))


@pytest.mark.parametrize("name", sorted(REFERENCES))
def test_reference_file_matches_contract(name: str) -> None:
    assert read_reference(REF, name).height > 0


def test_every_reference_file_has_a_contract() -> None:
    assert {path.stem for path in REF.glob("*.csv")} == set(REFERENCES)


def test_reason_codes_match_spec() -> None:
    expected = [
        (code, "counterparty" if code[0] == "C" else "exposure", text)
        for code, text in re.findall(r"^\| ([CR]\d{2}) \| (.+?) \|$", SPEC, re.MULTILINE)
    ]
    assert read_reference(REF, "reason_code").rows() == expected
    assert len(expected) == 19


def test_domains_match_spec() -> None:
    assert column("segment", "segment_code") == ["SOVEREIGN", "BANK", "CORPORATE", "SME", "RETAIL"]
    assert column("rating", "rating_code") == ["AAA", "AA", "A", "BBB", "BB", "B", "CCC", "NR"]
    assert column("product", "product_code") == ["LOAN", "UNDRAWN_LINE", "GUARANTEE"]
    assert column("collateral_type", "collateral_type") == ["CASH", "SOV_BOND", "CORP_BOND", "EQUITY"]


def test_lei_required_for_legal_entities() -> None:
    frame = read_reference(REF, "segment").filter(pl.col("lei_required") == "Y")
    assert frame["segment_code"].to_list() == ["SOVEREIGN", "BANK", "CORPORATE"]


def test_rating_buckets_and_ranks_match_spec() -> None:
    frame = read_reference(REF, "rating")
    assert frame["rating_bucket"].to_list() == ["AAA_AA", "AAA_AA", "A", "BBB", "BB", "B", "CCC_C", "NR"]
    assert frame["rating_rank"].to_list() == [str(rank) for rank in range(1, 9)]


def test_countries_are_iso_alpha_2() -> None:
    codes = column("country", "country_code")
    assert len(codes) == 249
    assert codes == sorted(codes)
    assert {"FR", "DE", "US", "GB"} <= set(codes)


def test_default_rates_match_spec() -> None:
    assert calibration("default_rate_annual") == S_AND_P | {"NR": S_AND_P["B"]}


def test_calibration_sources_given() -> None:
    frame = read_reference(REF, "calibration")
    sourced = frame.filter(pl.col("source") != "assumption")
    assert sourced["source"].str.contains(r"^(SPEC §3|S&P Global Ratings, .+)$").all()
    assumptions = frame.filter(pl.col("source") == "assumption")
    assert assumptions.height > 0
    assert (assumptions["rationale"].str.len_chars() > 0).all()


@pytest.mark.parametrize(("parameter", "reference"), sorted(SHARES.items()))
def test_shares_cover_domain_and_sum_to_one(parameter: str, reference: str) -> None:
    shares = calibration(parameter)
    assert set(shares) <= set(read_reference(REF, reference)[:, 0])
    assert sum(Decimal(value) for value in shares.values()) == 1


def test_rating_shares_per_segment() -> None:
    shares = calibration("rating_share")
    segments, ratings = column("segment", "segment_code"), column("rating", "rating_code")
    assert set(shares) == {f"{s}.{r}" for s in segments for r in ratings}
    for segment in segments:
        assert sum(Decimal(shares[f"{segment}.{r}"]) for r in ratings) == 1


def test_segment_keyed_parameters_cover_segments() -> None:
    segments = set(column("segment", "segment_code"))
    assert set(calibration("lei_share")) == segments
    assert set(calibration("amount_median")) == segments
    assert calibration("lei_share") == {"SOVEREIGN": "1", "BANK": "1", "CORPORATE": "1", "SME": "0.5", "RETAIL": "0"}


def test_reference_contract_violation_fails(tmp_path: Path) -> None:
    (tmp_path / "segment.csv").write_text("segment_code,lei_required,label\nRETAIL,maybe,Retail\n", encoding="utf-8")
    with pytest.raises(ContractError, match="column=lei_required"):
        read_reference(tmp_path, "segment")
    with pytest.raises(ContractError, match="unknown reference"):
        read_reference(tmp_path, "currency")
    with pytest.raises(ContractError, match="cannot read"):
        read_reference(tmp_path, "rating")


@pytest.mark.parametrize(
    ("rows", "check"),
    [
        ("p,,0.1,assumption,\n", "assumption_rationale"),
        ("p,,0.1,SPEC §3,\np,,0.2,SPEC §3,\n", "unique"),
        ("p,,-0.1,SPEC §3,\n", "str_matches"),
    ],
)
def test_calibration_contract_violation_fails(tmp_path: Path, rows: str, check: str) -> None:
    (tmp_path / "calibration.csv").write_text("parameter,key,value,source,rationale\n" + rows, encoding="utf-8")
    with pytest.raises(ContractError, match=check):
        read_reference(tmp_path, "calibration")
