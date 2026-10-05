# Architecture

## Context and components

```mermaid
flowchart TB
    operator([Operator]) -->|make, srdwh CLI| cli
    subgraph host[Developer host or CI runner]
        cli[srdwh: Typer CLI<br/>Polars, Pandera, python-oracledb thin]
        files[(data/: landing, ground_truth, exports)]
    end
    subgraph oracle[Oracle 26ai Free container, PDB FREEPDB1]
        owner[(SRDWH_OWNER<br/>tables, packages, views)]
        secschema[(SRDWH_SEC<br/>access table, context,<br/>VPD function, logon trigger)]
        policies[[VPD, Redaction, FGA,<br/>unified audit trail]]
    end
    cli <-->|Parquet| files
    cli -->|SRDWH_ETL session| owner
    profiles([Profile accounts]) -->|SQL client| owner
    secschema -.-> policies -.-> owner
```

| Component | Responsibility |
|---|---|
| `srdwh generate` | seeded, deterministic simulator: counterparties, exposures, injected faults, independent ground truth |
| `srdwh run` | run lock, ingestion, phase orchestration, exports; owns every transaction |
| `pkg_ops` | run lock, load registry, as_of state, run and step log, statistics |
| `pkg_silver` | coded rejects (first failing rule), typing, silver replacement per as_of, exact reconciliation |
| `pkg_gold` | SCD2 and SCD1 counterparty dimension, exposure facts, mart, counts check, rewind |
| `pkg_rwa` | standardised RWA chain with the parameter version valid at the as_of |
| `pkg_err` | autonomous error log used by every package and the logon trigger |
| `srdwh access-check` | one session per profile account, compared cell by cell with the access matrix |

Packages never commit; Python commits once per unit of work. Rows are processed set-based in SQL; Python loops only over
files, partitions and batches.

## Layers

| Layer | Tables | Rule |
|---|---|---|
| Landing | `data/landing/<feed>/as_of_date=YYYY-MM-DD/` | Parquet zstd plus a manifest written last |
| Operations | `OPS_LOAD_REGISTRY`, `OPS_ASOF_STATE`, `OPS_RUN_LOG`, `OPS_ERR_LOG` | one row per load, as_of, step and error |
| Reference, parameters | `REF_*`, `PARAM_CCF`, `PARAM_HAIRCUT`, `PARAM_RISK_WEIGHT` | loaded at deployment; a parameter change is a new version |
| Bronze | `BRZ_COUNTERPARTY`, `BRZ_EXPOSURE` | text as delivered, append-only, partitioned per load |
| Silver | `SLV_COUNTERPARTY`, `SLV_EXPOSURE`, `SLV_REJ_*` | typed and validated, replaced per as_of, rejects with a reason code |
| Gold | `GLD_DIM_*`, `GLD_FACT_EXPOSURE`, `GLD_FACT_RWA`, `GLD_MART_RWA` | star schema, monthly snapshots, local bitmap indexes |
| Views | `V_RWA_BY_CLASS`, `V_RWA_TREND`, `V_TOP_EXPOSURES` | COREP C 07.00 breakdown, 12-month trend, top 20 |

## Run sequence

```mermaid
sequenceDiagram
    participant CLI as srdwh run
    participant OPS as pkg_ops
    participant SLV as pkg_silver
    participant GLD as pkg_gold
    participant RWA as pkg_rwa
    CLI->>OPS: lock_run, start_run, fail_orphan_loads
    loop each ready partition
        CLI->>OPS: register_load
        CLI->>CLI: structural checks, direct path load to BRZ_
        CLI->>OPS: close_load
    end
    CLI->>OPS: silver_plan
    loop phase 1a, each as_of
        CLI->>SLV: reject_counterparties, reject_exposures
    end
    Note over CLI: a reject rate above the threshold exits 2 before any replacement
    loop phase 1b, each as_of
        CLI->>SLV: replace_as_of (exact reconciliation)
        CLI->>OPS: record_silver
    end
    CLI->>OPS: gold_start, rewind from D when needed
    loop phase 2, each as_of from D
        CLI->>GLD: build_as_of
        CLI->>RWA: compute
        CLI->>GLD: finish_as_of (mart, counts check)
        CLI->>CLI: export views, Parquet temp file then rename
        CLI->>OPS: record_gold
    end
    CLI->>OPS: gather_stats, log run
```

A rerun is idempotent: a delivered file with the same sha256 is skipped, an as_of whose silver and gold already match its
latest loads is not touched, and a late correction rewinds the gold from the corrected as_of.

## Gold model

```mermaid
erDiagram
    GLD_DIM_DATE ||--o{ GLD_FACT_EXPOSURE : date_sk
    GLD_DIM_COUNTERPARTY ||--o{ GLD_FACT_EXPOSURE : cpty_sk
    GLD_DIM_PRODUCT ||--o{ GLD_FACT_EXPOSURE : product_sk
    GLD_FACT_EXPOSURE ||--|| GLD_FACT_RWA : "as_of_date, exposure_id"
    GLD_FACT_RWA }o--|| GLD_MART_RWA : aggregates
    GLD_DIM_COUNTERPARTY {
        number cpty_sk
        string cpty_id
        string segment_code "SCD2"
        string rating "SCD2"
        string default_flag "SCD2"
        string cpty_name "SCD1, redacted"
        string lei "SCD1, redacted"
        date valid_from
        date valid_to
    }
```

Facts point to the counterparty version valid at their as_of. `segment_code` is copied onto the facts and the mart so the
row policy needs no join.

## RWA chain

| Step | Formula |
|---|---|
| Exposure class | `DEFAULTED` when `default_flag = Y`, else `segment_code` |
| Rating bucket | from `REF_RATING` (AAA and AA to AAA_AA, CCC to CCC_C) |
| EAD | `drawn_amt + CCF x undrawn_amt` |
| E* | `max(0, EAD - collateral_amt x (1 - Hc))`, with He = Hfx = 0 |
| RWA | `ROUND(E* x risk_weight, 2)`; intermediates stay unrounded |

Parameters carry a version and a validity range; the version valid at the as_of is recorded on every RWA row. The
golden set in `db/tests/fixtures/golden_rwa.sql` pins the chain to the cent (total 2,211,000.00).

## Security

```mermaid
flowchart LR
    logon[Logon] --> trg[SEC_LOGON_TRG]
    trg -->|SEC_USER_ACCESS row| ctx[(SRDWH_CTX:<br/>PROFILE, SEGMENT)]
    query[SELECT on gold] --> vpd{VPD predicate}
    ctx --> vpd
    vpd -->|pipeline, risk manager| allrows[all rows]
    vpd -->|analyst| seg[own segment]
    vpd -->|no profile| none[no row]
    query --> red[Redaction: names FULL,<br/>LEI last 4 visible]
    query --> fga[FGA: amounts, names, LEI<br/>read outside the pipeline]
    fga --> trail[(UNIFIED_AUDIT_TRAIL<br/>read by AUDITOR)]
```

- Roles `R_ANALYST`, `R_RISK_MANAGER`, `R_AUDITOR` grant SELECT on gold and views only; profile accounts receive
  ORA-00942 on bronze, silver, operations, reference, parameter and security objects.
- The context is set only by `pkg_sec_ctx`; the logon trigger never raises, so a failure leaves the session without a
  profile and therefore without rows.
- No application account holds an ANY privilege, an exemption, an audit administration role or the policy packages.

## Deployment

`docker compose up` runs `db/init` as SYS on the first start: `00_accounts.sh` creates the accounts from `.env`,
`10_deploy.sh` deploys `db/ddl` in name order and ends with a gate that fails on any invalid object or missing comment,
`20_dev_ci.sh` (dev and ci only) assigns the profiles and installs utPLSQL with the test suites. Environments are rebuilt
from `db/` rather than migrated. CI runs the same compose file and Makefile targets.

## Decisions

See [docs/adr](adr/).
