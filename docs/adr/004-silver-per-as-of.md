# ADR-004 Silver replaced per as_of after reject validation

- Status: accepted.
- Context: a degraded delivery must not overwrite good silver or gold, and exposures reference counterparties.
- Decision: phase 1a computes rejects and rates for every as_of to process without replacing anything; only if no
  rate exceeds the threshold does phase 1b replace silver as_of by as_of, with an exact reconciliation before commit.
- Consequences: exit 2 leaves the previous silver and gold intact; counterparty and exposure replacements stay
  consistent with the foreign key.
