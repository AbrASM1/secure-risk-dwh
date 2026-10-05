# ADR-003 Direct path ingestion into an append-only bronze

- Status: accepted.
- Context: feeds arrive as Parquet with a manifest; reloads and corrections must stay traceable.
- Decision: structural checks before any write, then `direct_path_load` in batches into text-typed `BRZ_` tables
  partitioned per load; bronze is never updated or deleted, and the ETL account cannot do so.
- Consequences: every delivered row stays traceable by `load_id` and `src_row`; a failed load is marked `FAILED` and
  reloaded, its orphan rows are ignored.
