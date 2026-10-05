# ADR-002 Set-based processing in the database, transactions owned by Python

- Status: accepted.
- Context: 50,000 exposures per month under a 1 GB Python budget, exact Oracle constraints, idempotent reruns.
- Decision: transformations are SQL statements in PL/SQL packages that never commit; `srdwh` calls them and commits once
  per unit of work. Python moves files and orchestrates; it never loops over rows.
- Consequences: data stays in the database, an error rolls back a whole unit, and the CLI decides every commit point.
