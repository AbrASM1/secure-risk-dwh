from dataclasses import dataclass

DENIED = "denied"
NONE = "none"
ALL = "all"
REDACTED = "redacted"
CLEAR = "clear"
MIXED = "mixed"
RECORDS = "records"
SESSION_PRIVS = "CREATE SESSION"


@dataclass(frozen=True)
class Expected:
    account: str
    roles: frozenset[str]
    detail: str
    names: str
    marts: str
    audit: str


@dataclass(frozen=True)
class Observed:
    account: str
    roles: frozenset[str]
    privs: frozenset[str]
    detail: frozenset[str] | None
    names: str
    marts: frozenset[str] | None
    hidden: frozenset[str]
    audit: str


@dataclass(frozen=True)
class Cell:
    account: str
    name: str
    expected: str
    observed: str

    @property
    def ok(self) -> bool:
        return self.expected == self.observed


EXPECTED = (
    Expected("ANALYST_CORP", frozenset({"R_ANALYST"}), "CORPORATE", REDACTED, "CORPORATE", DENIED),
    Expected("ANALYST_RETAIL", frozenset({"R_ANALYST"}), "RETAIL", REDACTED, "RETAIL", DENIED),
    Expected("RISK_MANAGER", frozenset({"R_RISK_MANAGER"}), ALL, CLEAR, ALL, DENIED),
    Expected("PROBE_NOPROFILE", frozenset({"R_ANALYST"}), NONE, NONE, NONE, DENIED),
    Expected("AUDITOR", frozenset({"R_AUDITOR", "AUDIT_VIEWER"}), DENIED, DENIED, ALL, RECORDS),
)
COLUMNS = ("roles", "privs", "detail", "names", "marts", "hidden", "audit")


def names_state(rows: int, masked: int) -> str:
    if rows == 0:
        return NONE
    if masked == rows:
        return REDACTED
    return CLEAR if masked == 0 else MIXED


def cells(expected: Expected, observed: Observed, segments: frozenset[str]) -> tuple[Cell, ...]:
    pairs = (
        (_joined(expected.roles), _joined(observed.roles)),
        (SESSION_PRIVS, _joined(observed.privs)),
        (_resolved(expected.detail, segments), _segments(observed.detail)),
        (expected.names, observed.names),
        (_resolved(expected.marts, segments), _segments(observed.marts)),
        (DENIED, _joined(observed.hidden) or DENIED),
        (expected.audit, observed.audit),
    )
    return tuple(Cell(expected.account, name, want, got) for name, (want, got) in zip(COLUMNS, pairs, strict=True))


def render(matrix: tuple[Cell, ...]) -> str:
    accounts = dict.fromkeys(cell.account for cell in matrix)
    lines = [" ".join([f"{'account':<16}", *(f"{name:<8}" for name in COLUMNS)])]
    for account in accounts:
        row = [cell for cell in matrix if cell.account == account]
        lines.append(" ".join([f"{account:<16}", *(f"{'ok' if c.ok else 'KO':<8}" for c in row)]))
    lines += [f"{c.account} {c.name}: expected {c.expected}, observed {c.observed}" for c in matrix if not c.ok]
    return "\n".join(lines)


def _resolved(spec: str, segments: frozenset[str]) -> str:
    if spec == ALL:
        return _segments(segments)
    return spec


def _segments(found: frozenset[str] | None) -> str:
    if found is None:
        return DENIED
    return _joined(found) or NONE


def _joined(values: frozenset[str]) -> str:
    return ",".join(sorted(values))
