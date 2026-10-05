# ADR-001 Ephemeral environments rebuilt from db/

- Status: accepted.
- Context: dev and CI run Oracle Free in a container with a 12 GB data limit; the schema evolves with every step.
- Decision: every environment is rebuilt from `db/` by `make reset`; no migration tool, no in-place upgrade.
- Consequences: one deployment path for dev and CI, a deploy gate that rejects invalid objects and missing comments;
  production would need a migration tool, out of scope for v1.
