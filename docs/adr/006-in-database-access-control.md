# ADR-006 Access control in the database

- Status: accepted.
- Context: analysts query the gold directly with SQL clients; no application layer filters their reads.
- Decision: a schema-only `SRDWH_SEC` owns the access table, the application context, the VPD function and a logon
  trigger; VPD filters rows by segment, Redaction masks names and LEI, FGA records sensitive reads for the auditor.
- Consequences: every client is filtered the same way and denied by default; an inference through filters on a
  redacted column stays possible and is detected through FGA, not prevented.
