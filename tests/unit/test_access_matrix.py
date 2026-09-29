from dataclasses import replace

import pytest

from srdwh.access.matrix import (
    ALL,
    CLEAR,
    DENIED,
    EXPECTED,
    MIXED,
    NONE,
    RECORDS,
    REDACTED,
    Expected,
    Observed,
    cells,
    names_state,
    render,
)

SEGMENTS = frozenset({"BANK", "CORPORATE", "RETAIL", "SME", "SOVEREIGN"})
ANALYST = Expected("ANALYST_CORP", frozenset({"R_ANALYST"}), "CORPORATE", REDACTED, "CORPORATE", DENIED)


BASE = Observed(
    account="ANALYST_CORP",
    roles=frozenset({"R_ANALYST"}),
    privs=frozenset({"CREATE SESSION"}),
    detail=frozenset({"CORPORATE"}),
    names=REDACTED,
    marts=frozenset({"CORPORATE"}),
    hidden=frozenset(),
    audit=DENIED,
)


@pytest.mark.parametrize(("rows", "masked", "state"), [(0, 0, NONE), (5, 5, REDACTED), (5, 0, CLEAR), (5, 2, MIXED)])
def test_names_state(rows: int, masked: int, state: str) -> None:
    assert names_state(rows, masked) == state


def test_matching_observation_is_all_ok() -> None:
    matrix = cells(ANALYST, BASE, SEGMENTS)
    assert [cell.name for cell in matrix] == ["roles", "privs", "detail", "names", "marts", "hidden", "audit"]
    assert all(cell.ok for cell in matrix)
    assert "KO" not in render(matrix)


def test_other_segment_visible_is_reported() -> None:
    matrix = cells(ANALYST, replace(BASE, detail=frozenset({"CORPORATE", "RETAIL"})), SEGMENTS)
    assert [cell.name for cell in matrix if not cell.ok] == ["detail"]
    assert "ANALYST_CORP detail: expected CORPORATE, observed CORPORATE,RETAIL" in render(matrix)


def test_visible_hidden_layer_and_missing_grant_are_reported() -> None:
    matrix = cells(ANALYST, replace(BASE, hidden=frozenset({"REF_SEGMENT"}), marts=None), SEGMENTS)
    assert {(cell.name, cell.observed) for cell in matrix if not cell.ok} == {
        ("hidden", "REF_SEGMENT"),
        ("marts", DENIED),
    }


def test_all_resolves_to_every_segment_and_empty_to_none() -> None:
    manager = next(expected for expected in EXPECTED if expected.account == "RISK_MANAGER")
    assert manager.detail == ALL
    seen = replace(
        BASE, account="RISK_MANAGER", roles=frozenset({"R_RISK_MANAGER"}), detail=SEGMENTS, names=CLEAR, marts=SEGMENTS
    )
    matrix = cells(manager, seen, SEGMENTS)
    assert all(cell.ok for cell in matrix)
    assert cells(manager, seen, frozenset())[2].expected == NONE


def test_auditor_expects_records_and_no_detail() -> None:
    auditor = EXPECTED[-1]
    assert (auditor.account, auditor.detail, auditor.names, auditor.audit) == ("AUDITOR", DENIED, DENIED, RECORDS)
