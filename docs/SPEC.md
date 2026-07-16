# secure-risk-dwh | SPEC

## 0. Purpose
Credit-risk data platform on Oracle: counterparty and exposure feeds -> medallion DWH -> standardised-approach credit RWA -> row, column and audit controls on the result.
No client data in this repository: dev and ci run on feed simulator output (F1), built to the production feed contract.

## 1. Scope v1
- In: F1 to F11. Optional, only when requested: F12 (§17).
- Out: IRB, output floor, maturity-dependent haircuts, SCRA (unrated banks take 1.00), currencies other than EUR, market and operational risk, UI, schema migration tooling (ADR-001), retention and purge, Spark, Delta, Iceberg, Airflow, Dagster, Kafka.

## 2. Accounts and access matrix
| Account | Kind | Use |
|---|---|---|
| SRDWH_OWNER | login; system privilege CREATE SESSION only; EXECUTE on DBMS_LOCK | owns data objects and pipeline packages; deploy-time tests only |
| SRDWH_SEC | schema-only (NO AUTHENTICATION) | owns SEC_USER_ACCESS, context SRDWH_CTX, pkg_sec_ctx, VPD function, logon trigger |
| SRDWH_ETL | login | pipeline runtime |
| ANALYST_CORP, ANALYST_RETAIL, RISK_MANAGER, AUDITOR | login, dev and ci only | profiles below |
| PROBE_NOPROFILE | login, dev and ci only | R_ANALYST without SEC_USER_ACCESS row: must see nothing |

| Account | Role | Detail rows | cpty_name, lei | Marts | Audit trail |
|---|---|---|---|---|---|
| ANALYST_CORP | R_ANALYST | segment CORPORATE | redacted | segment CORPORATE | no |
| ANALYST_RETAIL | R_ANALYST | segment RETAIL | redacted | segment RETAIL | no |
| RISK_MANAGER | R_RISK_MANAGER | all | clear | all | no |
| AUDITOR | R_AUDITOR | no grant | no grant | all | FGA records |
| SRDWH_ETL | direct grants | all | clear | all | no |

- Default deny: a session without profile sees no row of the VPD-protected tables (§9). Profile accounts get ORA-00942 on BRZ_, SLV_, OPS_, REF_, PARAM_ and SEC_ objects.
- SRDWH_ETL: INSERT and SELECT on BRZ_ (never UPDATE, DELETE, MERGE, TRUNCATE), SELECT on OPS_LOAD_REGISTRY and V_ views, EXECUTE on pipeline packages, no other DML.
- No application account holds DBA, an ANY privilege, EXEMPT ACCESS POLICY, EXEMPT REDACTION POLICY, AUDIT_ADMIN, ADMINISTER REDACTION POLICY, or EXECUTE on DBMS_RLS, DBMS_REDACT, DBMS_FGA. The deployment creates the security policies (SYS in dev and ci).
- Quota on USERS for SRDWH_OWNER and SRDWH_SEC. Passwords from environment variables only; ci generates them per job (24 chars [A-Za-z0-9], first char a letter).

## 3. F1 Feed simulator (Python)
- Deterministic: numpy Generator(seed). Same seed, profile and uv.lock -> byte-identical files (sha256): rows sorted by id, fixed row-group size and zstd level.
- Profiles in srdwh.toml: dev = 5,000 counterparties, 50,000 exposures, 12 month-ends; ci = 500, 2,000, 3. Each profile sets seed and first as_of.
- Counterparty feed: cpty_id, cpty_name (vectorised vocabularies, no Faker: legal-entity names, person names for RETAIL), lei, segment_code {SOVEREIGN, BANK, CORPORATE, SME, RETAIL}, country, rating {AAA, AA, A, BBB, BB, B, CCC, NR}, default_flag {Y, N}, as_of_date. LEI present for every SOVEREIGN, BANK and CORPORATE counterparty, for about half of SME, never for RETAIL.
- Calibration: db/ref/calibration.csv, one row per parameter with its source, or the word assumption. Monthly default probability per rating = 1 - (1 - annual)^(1/12), annual from the S&P 2024 Annual Global Corporate Default And Rating Transition Study, table 4, weighted long-term average: AAA 0.00%, AA 0.02%, A 0.05%, BBB 0.14%, BB 0.56%, B 2.93%, CCC 26.12% (CCC/C). Assumptions: NR uses the B rate, about 1% of counterparties a month move one notch, 0.1% change name.
- Exposure feed: exposure_id, cpty_id, product_code {LOAN, UNDRAWN_LINE, GUARANTEE}, drawn_amt, undrawn_amt, collateral_amt, collateral_type {CASH, SOV_BOND, CORP_BOND, EQUITY or empty}, currency, as_of_date. The book persists across month-ends: about 2% replaced, amounts drift within 5%.
- Domain values come from db/ref/*.csv, the single source also loaded into REF_ tables at deploy.
- LEI: 18 chars [A-Z0-9] plus ISO 17442 check digits (ISO 7064 MOD 97-10), computed vectorised.
- Files carry text only: every column Utf8, empty string when missing.
- Faults: at least one row per rule code of F3 in every as_of, then up to 1% of exposure rows and 0.5% of counterparty rows. Exposure faults go on otherwise clean rows of clean counterparties. Duplicates (C08, R06) are added copies of clean rows.
- Ground truth: data/ground_truth/<feed>/as_of_date=YYYY-MM-DD/expected.parquet (src_row, reason_code). Expected code = first failing rule in code order, R07 cascades of rejected counterparties included. Never ingested.
- Output: data/landing/<feed>/as_of_date=YYYY-MM-DD/part-0.parquet, then manifest.json {feed, as_of_date, rows, sha256, seed, profile, contract_version} written last. src_row = 1-based row index in the file.
- Feed contracts (names, order, Utf8, max lengths, contract_version): one Pandera module, used by F1 on write and F2 on read.

## 4. F2 Ingestion (Python -> bronze)
- A partition without manifest.json is not ready: skipped and logged. Per as_of, the counterparty feed loads first.
- Structural checks, fail fast with exit 1: known contract_version, sha256 and row count match the manifest, schema matches the contract.
- OPS_LOAD_REGISTRY(load_id, feed, as_of_date, file, sha256, rows_expected, rows_loaded, rows_rejected, status {STARTED, LOADED, FAILED}, started_at, ended_at, message), written through pkg_ops. rows_rejected is set by the silver rules (§5, phase 1a of §10).
- A file is skipped only if a LOADED entry has the same feed, as_of_date and sha256. FAILED entries never block a retry.
- Load: register STARTED and commit, Connection.direct_path_load (batch_size from config) into BRZ_COUNTERPARTY or BRZ_EXPOSURE, then LOADED if bronze holds rows_expected rows for the load_id, else FAILED. Direct path commits implicitly: rows of a FAILED load stay in bronze and are never read.
- Bronze: feed columns VARCHAR2(4000) as delivered, plus load_id, src_file, src_row, ingested_at (UTC), all supplied by the loader. No constraint, index or trigger. Append-only.

## 5. F3 Silver (pkg_silver, set-based)
- Input per feed and as_of: the latest LOADED load. Counterparties first: R07 reads the counterparties of the counterparty load being processed that pass C01 to C08.
- Text values are TRIMmed, then matched case-sensitively. Domains come from REF_ tables (REF_SEGMENT, REF_RATING, REF_PRODUCT, REF_COLLATERAL_TYPE, REF_COUNTRY = ISO 3166-1 alpha-2), never literal lists in rule SQL. Reason codes live in REF_REASON_CODE (code, feed, rule text, from db/ref).
- Amount: ^-?[0-9]{1,16}(\.[0-9]{1,2})?$, then TO_NUMBER with explicit format and NLS_NUMERIC_CHARACTERS. Empty collateral_amt means 0. Date: exactly YYYY-MM-DD, TO_DATE with FX and DEFAULT NULL ON CONVERSION ERROR.
- Rules in code order, the first failing rule wins:

| Code | Counterparty rule |
|---|---|
| C01 | cpty_id or cpty_name empty or over contract length |
| C02 | as_of_date invalid or different from the file partition |
| C03 | segment_code not in REF_SEGMENT |
| C04 | rating not in REF_RATING |
| C05 | default_flag not Y or N |
| C06 | lei empty for SOVEREIGN, BANK or CORPORATE, or lei present and not ^[A-Z0-9]{18}[0-9]{2}$ or with MOD 97-10 remainder (A=10 to Z=35) not 1, computed set-based over position rows |
| C07 | country not in REF_COUNTRY |
| C08 | cpty_id duplicated in the load, every occurrence |

| Code | Exposure rule |
|---|---|
| R01 | exposure_id or cpty_id empty or over contract length |
| R02 | drawn_amt or undrawn_amt not an amount, or collateral_amt neither empty nor an amount |
| R03 | an amount < 0 |
| R04 | product_code not in REF_PRODUCT |
| R05 | as_of_date invalid or different from the file partition |
| R06 | exposure_id duplicated in the load, every occurrence |
| R07 | cpty_id not among the accepted counterparties of the same as_of (counterparty load being processed) |
| R08 | collateral_amt > 0 and collateral_type empty |
| R09 | collateral_type neither empty nor in REF_COLLATERAL_TYPE |
| R10 | LOAN with undrawn_amt > 0, or GUARANTEE with drawn_amt > 0 |
| R11 | currency not EUR |

- Rejects: SLV_REJ_COUNTERPARTY, SLV_REJ_EXPOSURE (load_id, src_row, as_of_date, reason_code FK to REF_REASON_CODE, raw columns), replaced per load_id.
- SLV_COUNTERPARTY, SLV_EXPOSURE: typed, PK (as_of_date, id), FK exposure -> counterparty, FKs to REF_, load_id on every row, monthly interval partitioning.
- Reconciliation per load that reaches silver, exact: bronze rows = silver rows + rejected rows.
- Reject rate = rejected / bronze rows of the load. Above reject_threshold (config, 0.05) for either feed of any as_of processed by the run: no silver or gold is replaced for any as_of, the rejects and reject counts are kept, the run exits 2 (§10).
- Two units of work per as_of, no DDL: (1) in phase 1a, rejects of the counterparty load, then of the exposure load, replaced per load_id and committed with their reject counts; a counterparty breach skips the exposure rules of that as_of; (2) in phase 1b only, one transaction replaces SLV_COUNTERPARTY and SLV_EXPOSURE of the as_of (DELETE exposures, DELETE counterparties, INSERT counterparties, INSERT exposures) and records its silver loads in OPS_ASOF_STATE.

## 6. F4 Gold (pkg_gold)
| Table | Grain and rules |
|---|---|
| GLD_DIM_DATE | one row per day, 2000-01-01 to 2040-12-31, seeded at deploy: date_sk YYYYMMDD, month, quarter, year, is_month_end |
| GLD_DIM_PRODUCT | from REF_PRODUCT: product_sk, product_code, product_type |
| GLD_DIM_COUNTERPARTY | cpty_sk identity, cpty_id. SCD2 on segment_code, rating, default_flag. SCD1 on cpty_name, lei, country, overwritten on every version. valid_from inclusive, valid_to exclusive, open version valid_to = DATE '9999-12-31', is_current |
| GLD_FACT_EXPOSURE | one row per exposure_id per as_of: date_sk, cpty_sk of the version valid at as_of, product_sk, segment_code (denormalised for VPD), exposure_id, amounts NUMBER(18,2), run_id. Monthly interval partitioning on as_of_date |
| GLD_FACT_RWA | same grain and keys, plus exposure_class, rating_bucket, ccf, ead, hc, e_star, risk_weight, rwa NUMBER(20,2), param_version; ead and e_star exact NUMBER(30,6) |
| GLD_MART_RWA | per as_of x segment_code x exposure_class x risk_weight: n_exposures, ead, e_star, rwa |

- GLD_FACT_EXPOSURE and GLD_FACT_RWA are monthly periodic snapshots: amounts add across exposures, never across as_of.
- A version starts at the as_of where its change is first seen. A counterparty missing from a snapshot keeps its current version.
- Fact FKs RELY DISABLE NOVALIDATE. Local bitmap indexes on fact FKs and segment_code. Integrity is proven by invariant tests.
- Invariants: no overlapping versions, exactly one current version per cpty_id, unique fact grain, each fact row on the version valid at its as_of, per as_of silver exposures = GLD_FACT_EXPOSURE rows = GLD_FACT_RWA rows.
- Unit of work per as_of: dimension, facts, RWA and mart in one transaction (DELETE then INSERT, no DDL). Statistics are gathered after the commit, DBMS_STATS commits implicitly.
- Rewind from D: delete fact, RWA and mart rows with as_of >= D, delete versions with valid_from >= D, reopen versions with valid_from < D and valid_to >= D (valid_to = 9999-12-31, is_current = Y).

## 7. F5 RWA (pkg_rwa, set-based)
1. exposure_class = DEFAULTED if default_flag = Y, else segment_code.
2. rating_bucket: AAA and AA -> AAA_AA, A, BBB, BB, B, CCC -> CCC_C, NR.
3. EAD = drawn_amt + CCF(product_code) x undrawn_amt.
4. E* = max(0, EAD x (1 + He) - C x (1 - Hc - Hfx)): C = collateral_amt, Hc = haircut of collateral_type (0 when empty), He = 0, Hfx = 0 (EUR only).
5. RWA = ROUND(E* x RW(exposure_class, rating_bucket), 2). Intermediates stay unrounded.

- PARAM_CCF, PARAM_HAIRCUT, PARAM_RISK_WEIGHT carry param_version, valid_from, valid_to; ccf and haircut lie in [0, 1], risk_weight in [0, 12.5]. The version valid at as_of applies. A change is a new version, never an UPDATE. No overlap. PARAM_RISK_WEIGHT holds exactly one row per class and bucket per version (6 x 7).
- Parameter set v1, owned by Risk, derived from BCBS CRE20 and CRE22, valid from 2000-01-01:
  - PARAM_CCF: LOAN 0, UNDRAWN_LINE 0.40, GUARANTEE 1.00.
  - PARAM_HAIRCUT: CASH 0, SOV_BOND 0.02, CORP_BOND 0.06, EQUITY 0.20.
  - PARAM_RISK_WEIGHT:

| Class | AAA_AA | A | BBB | BB | B | CCC_C | NR |
|---|---|---|---|---|---|---|---|
| SOVEREIGN | 0 | 0.20 | 0.50 | 1.00 | 1.00 | 1.50 | 1.00 |
| BANK | 0.20 | 0.30 | 0.50 | 1.00 | 1.00 | 1.50 | 1.00 |
| CORPORATE | 0.20 | 0.50 | 0.75 | 1.00 | 1.50 | 1.50 | 1.00 |
| SME | 0.85 | 0.85 | 0.85 | 0.85 | 0.85 | 0.85 | 0.85 |
| RETAIL | 0.75 | 0.75 | 0.75 | 0.75 | 0.75 | 0.75 | 0.75 |
| DEFAULTED | 1.50 | 1.50 | 1.50 | 1.50 | 1.50 | 1.50 | 1.50 |

Golden set: single source db/tests/fixtures/golden_rwa.sql on as_of 2000-01-31, outside simulator dates, used by utPLSQL and by pytest in a rolled-back transaction, exact to the cent:

| Id | Segment | Rating | Default | Product | Drawn | Undrawn | Collateral | EAD | E* | RW | RWA |
|---|---|---|---|---|---|---|---|---|---|---|---|
| G1 | CORPORATE | AA | N | LOAN | 1,000,000 | 0 | none | 1,000,000 | 1,000,000 | 0.20 | 200,000.00 |
| G2 | CORPORATE | BBB | N | UNDRAWN_LINE | 0 | 500,000 | none | 200,000 | 200,000 | 0.75 | 150,000.00 |
| G3 | CORPORATE | A | N | LOAN | 1,000,000 | 0 | CORP_BOND 600,000 | 1,000,000 | 436,000 | 0.50 | 218,000.00 |
| G4 | RETAIL | NR | N | LOAN | 50,000 | 0 | CASH 60,000 | 50,000 | 0 | 0.75 | 0.00 |
| G5 | SOVEREIGN | AA | N | LOAN | 10,000,000 | 0 | none | 10,000,000 | 10,000,000 | 0 | 0.00 |
| G6 | BANK | A | N | UNDRAWN_LINE | 200,000 | 300,000 | none | 320,000 | 320,000 | 0.30 | 96,000.00 |
| G7 | SME | NR | N | LOAN | 300,000 | 0 | EQUITY 100,000 | 300,000 | 220,000 | 0.85 | 187,000.00 |
| G8 | CORPORATE | B | Y | LOAN | 400,000 | 0 | none | 400,000 | 400,000 | 1.50 | 600,000.00 |
| G9 | CORPORATE | BB | N | GUARANTEE | 0 | 250,000 | none | 250,000 | 250,000 | 1.00 | 250,000.00 |
| G10 | SOVEREIGN | BBB | N | LOAN | 2,000,000 | 0 | SOV_BOND 1,000,000 | 2,000,000 | 1,020,000 | 0.50 | 510,000.00 |

Total RWA: 2,211,000.00.

## 8. F6 Outputs
- V_RWA_BY_CLASS (per as_of, exposure_class and risk_weight: n_exposures, exposure_value = SUM(e_star), rwea = SUM(rwa); COREP C 07.00 risk-weight breakdown, v1 subset) and V_RWA_TREND (last 12 as_of per segment_code: ead, rwa, rwa_density = SUM(rwa) / NULLIF(SUM(ead), 0)) read GLD_MART_RWA only.
- V_TOP_EXPOSURES (top 20 by rwa per as_of, ties broken by exposure_id: exposure_id, cpty_id, segment_code, exposure_class, ead, rwa) reads GLD_FACT_RWA.
- Exports: data/exports/<view>/as_of_date=YYYY-MM-DD/part-0.parquet (zstd) for each as_of processed. fetch_df_all(fetch_decimals=True) then Polars, temp file then atomic rename, a rerun overwrites.
- No export, log line or error message contains cpty_name or lei.
- Money: delivered amounts NUMBER(18,2); derived amounts and sums in exact NUMBER sized for any valid input (rwa NUMBER(20,2), ead and e_star NUMBER(30,6), sums of rwa NUMBER(28,2)); Decimal in Arrow and Parquet, never float.

## 9. F7 Security (db/ddl/90_security.sql)
- Roles: R_ANALYST and R_RISK_MANAGER get SELECT on GLD_ tables and V_ views. R_AUDITOR gets SELECT on GLD_MART_RWA, V_RWA_BY_CLASS, V_RWA_TREND, plus AUDIT_VIEWER. Role grants follow SEC_USER_ACCESS, PROBE_NOPROFILE excepted.
- SEC_USER_ACCESS(username PK, profile {ANALYST, RISK_MANAGER, AUDITOR}, segment_code set only for ANALYST): one segment per analyst.
- CREATE CONTEXT SRDWH_CTX USING SRDWH_SEC.PKG_SEC_CTX. An AFTER LOGON ON DATABASE trigger calls it to set PROFILE and SEGMENT for SESSION_USER. The trigger never raises: on error the context stays unset (deny) and pkg_err logs it.
- VPD (DBMS_RLS, CONTEXT_SENSITIVE, function in SRDWH_SEC) on GLD_FACT_EXPOSURE, GLD_FACT_RWA, GLD_DIM_COUNTERPARTY, GLD_MART_RWA. Roles are disabled in definer's rights code, so the function reads SESSION_USER and SRDWH_CTX only:
  - SESSION_USER SRDWH_OWNER or SRDWH_ETL: no predicate
  - PROFILE RISK_MANAGER: no predicate. PROFILE AUDITOR: no predicate on GLD_MART_RWA
  - PROFILE ANALYST: segment_code = SYS_CONTEXT('SRDWH_CTX', 'SEGMENT')
  - anything else, unset context included: 1=0
- Redaction (DBMS_REDACT) on GLD_DIM_COUNTERPARTY: cpty_name FULL, lei PARTIAL with the last 4 characters visible. Expression: SYS_CONTEXT('USERENV','SESSION_USER') NOT IN ('SRDWH_OWNER','SRDWH_ETL') AND SYS_CONTEXT('SYS_SESSION_ROLES','R_RISK_MANAGER') = 'FALSE'. Redaction applies only when the expression is TRUE: never compare a context that can be NULL there.
- FGA (DBMS_FGA): SELECT on GLD_FACT_EXPOSURE (drawn_amt, undrawn_amt) and GLD_DIM_COUNTERPARTY (cpty_name, lei). audit_condition SYS_CONTEXT('USERENV','SESSION_USER') NOT IN ('SRDWH_OWNER','SRDWH_ETL'), a single predicate (DBMS_FGA rejects AND and OR). Records land in UNIFIED_AUDIT_TRAIL with FGA_POLICY_NAME. AUDITOR queries it directly. Visibility can lag: tests poll up to 30 s.
- srdwh access-check: connects as each profile account, runs the reference queries, compares with §2 (rows per segment, redaction, ORA-00942 outside grants, FGA records, SESSION_ROLES and SESSION_PRIVS), prints the matrix, exits 0 only if every cell matches.

## 10. F8 Orchestration and operations
- srdwh run takes the run lock (DBMS_LOCK, fixed lock id, session-scoped, never ALLOCATE_UNIQUE which commits). A concurrent run exits 1 with no side effect. The run then marks leftover STARTED loads FAILED, ingests and processes.
- OPS_ASOF_STATE(as_of_date, slv_cpty_load_id, slv_expo_load_id, gld_cpty_load_id, gld_expo_load_id, slv_at, gld_at) records the loads in silver and in gold per as_of; gold loads are empty while gold of the as_of is absent or rewound. Silver of an as_of is dirty when the latest LOADED load of a feed differs from its silver load; gold is dirty when its loads are empty or differ from silver. D = earliest as_of with dirty silver or gold. Nothing dirty: no-op, exit 0. A feed missing for an as_of with dirty silver: exit 1.
- Phase 1a: rejects and reject counts of every as_of with dirty silver, in ascending order, committed per as_of, no silver replaced. If any reject rate exceeds reject_threshold: exit 2, silver and gold unchanged for every as_of.
- Phase 1b, only if no as_of breached: silver replaced for each of these as_of in ascending order, one transaction each (§5).
- Phase 2: rewind from D in its own transaction when D <= latest as_of in gold, then gold rebuilt for every as_of >= D in ascending order (§6). Gold loads are recorded once gold and exports of the as_of are complete.
- An interrupted run leaves OPS_ASOF_STATE consistent with the committed data: the next run resumes from it.
- srdwh run --rebuild-from D forces D: silver and gold of every as_of >= D are treated as dirty.
- Packages never COMMIT or ROLLBACK: the caller owns the transaction. pkg_err is the only autonomous transaction.
- pkg_err logs run_id, step, SQLCODE, message and DBMS_UTILITY.FORMAT_ERROR_BACKTRACE to OPS_ERR_LOG, then re-raises. WHEN OTHERS without re-raise exists only in the logon trigger.
- OPS_RUN_LOG(run_id, step, as_of_date, started_at, ended_at, rows_in, rows_out, rows_rejected, status, message).
- Logs: JSON lines on stdout with run_id, step, as_of, rows, duration_ms; the last line carries peak RSS. Every connection sets client_identifier = run_id, module = srdwh, action = step. Timestamps in UTC.
- Exit codes: 0 ok, 1 failure, 2 data-quality threshold breach.
- Config: srdwh.toml (profiles, batch_size, reject_threshold) plus environment (DSN, accounts, passwords), validated at start into frozen dataclasses. An unknown key fails.
- NFR: dev profile end to end under 10 min within the Free limits, image download excluded. Python peak RSS < 1 GB. DB connect retries bounded to 60 s.

## 11. F9 Tests
| Level | Tool | Must cover |
|---|---|---|
| Unit | pytest | simulator determinism, contracts, fault rates and ground truth, LEI check digits, config validation, exit codes |
| DB unit | utPLSQL as SRDWH_OWNER, rollback per test | each C and R rule with its boundaries, SCD2 invariants and rewind, fact grain, golden set, reconciliation, parameter versioning |
| Integration, marker db | pytest + oracledb | skip and retry of loads, e2e on ci profile, rerun no-op, late correction, rebuild-from, DQ breach, concurrent run, access matrix, exports |

- Gold comparisons (A6): order-independent checksum per table over natural keys and attributes, surrogate keys and run_id excluded.
- pytest-cov: fail under 80% on src/srdwh.
- LEI oracle: db/tests/fixtures/lei_gleif_sample.csv holds 1,000 LEI codes from GLEIF (Golden Copy or API, CC0, codes only; SOURCE.md beside it gives origin and extraction date). Every code passes the simulator check and C06; every code with one character replaced by another of the same class (digit for digit, letter for letter) fails both. A cross-class replacement changes the digit count of the MOD 97-10 number and can pass: 3,540 of the 700,000 single-character variants of the sample do.

## 12. F10 CI (GitHub Actions)
- Workflow permissions: contents read. Third-party actions pinned by commit SHA. Dependabot weekly on github-actions and uv.
- Job quality: ruff check, ruff format --check, mypy --strict, sqlfluff lint, gitleaks on full history, bronze check (no UPDATE, DELETE, MERGE or TRUNCATE on BRZ_ in db/ddl, db/init and src/), pytest -m "not db".
- Job db, needs quality: make setup, random passwords per job, docker compose up --wait with the same docker-compose.yml as dev, utPLSQL-cli with JUnit reporter, pytest -m db, srdwh access-check, JUnit reports uploaded.
- README badge. Pipeline under 15 min.

## 13. F11 Packaging
- docker-compose.yml: service oracle, image gvenzl/oracle-free:23.26.1-faststart (exact tag), port 127.0.0.1:1521, healthcheck healthcheck.sh, ./db/init on /container-entrypoint-initdb.d, ./db/ddl, ./db/ref, ./db/tests and .cache/utplsql read-only under /opt/srdwh, environment from .env, named volume dropped by make reset.
- The image runs every file under /container-entrypoint-initdb.d, recursively, as SYS (.sql in CDB root). db/init holds only executable .sh entry points; each opens FREEPDB1 with WHENEVER SQLERROR EXIT FAILURE.
- db/init: 00_accounts.sh (accounts and roles; profile accounts in dev and ci only). 10_deploy.sh runs db/ddl in order: each file sets CURRENT_SCHEMA, nothing is created in SYS, REF_ tables load db/ref/*.csv, and the script fails if an object is INVALID, if USER_ERRORS is not empty, or if a table or column has no COMMENT. 20_dev_ci.sh, dev and ci only: SEC_USER_ACCESS rows and role grants, R_ANALYST to PROBE_NOPROFILE, utPLSQL v3.2.3, db/tests. SRDWH_ENV (dev or ci) gates every dev-and-ci-only step.
- utPLSQL v3.2.3 (release tag v.3.2.3) and utPLSQL-cli: pinned and sha256-checked by make setup into .cache/ (gitignored).
- .sh committed as 100755. .gitattributes forces LF on *.sh, *.sql and *.csv.
- Makefile targets of CLAUDE.md. .env.example lists every variable without value.
- README: purpose, Mermaid architecture, 3-command quickstart (Linux, macOS, Windows through WSL2), configuration, security model (§2 matrix), dev-profile baseline (rows loaded, load time, total RWA, test count), links to docs/architecture.md, docs/runbook.md and the ADRs, statement "no client data: feeds are simulator output".
- docs/runbook.md: run, rerun, late delivery, rebuild-from, DQ breach, exit codes, logs, access-check, reset. docs/architecture.md: layers, data flow, accounts and security model, unit of work, as_of state.
- ADR-001: environments are ephemeral and rebuilt from db/, no migration tool in v1; a DDL change applies through make reset.

## 14. Acceptance (must pass)
| Id | Criterion |
|---|---|
| A1 | Fresh clone: make setup then make e2e exits 0 in under 10 min (dev profile, image download excluded) |
| A2 | Same seed, profile and uv.lock: identical landing sha256 and identical gold totals |
| A3 | Second run on the same landing: every file skipped, no-op, gold unchanged |
| A4 | Every ground-truth row rejected with its expected code, none reaches gold, reconciliation exact per load |
| A5 | Golden set exact to the cent, total 2,211,000.00; fact vs mart RWA difference = 0 per as_of |
| A6 | SCD2 invariants hold; a late correction of a past as_of and rebuild-from both equal a fresh full run |
| A7 | srdwh access-check exits 0: §2 holds, ORA-00942 outside grants, PROBE_NOPROFILE sees no row of the VPD-protected tables |
| A8 | Analyst detail reads leave FGA records readable by AUDITOR within 30 s; pipeline accounts leave none |
| A9 | CI green on main with badge, all suites pass, coverage >= 80% |
| A10 | gitleaks clean on full history; passwords only from environment |
| A11 | SRDWH_ETL gets ORA-01031 on UPDATE, DELETE, MERGE and TRUNCATE of BRZ_; bronze check clean |
| A12 | Reject rate above threshold for any as_of of a run: exit 2, rejects and reject counts kept, silver and gold of every as_of unchanged |
| A13 | Concurrent run exits 1 without side effect; a killed run leaves nothing blocking the next one |
| A14 | Python peak RSS < 1 GB on dev profile |

## 15. Milestones
| M | Content | Sections | Acceptance | Estimate |
|---|---|---|---|---|
| M0 | scaffold: uv, ruff, mypy, sqlfluff, pre-commit, gitleaks, Makefile, compose, db/init skeleton, quality job, Dependabot | 12, 13 | A10 | 1.5 h |
| M1 | feed simulator, contracts, db/ref, calibration, GLEIF sample, ground truth | 3, 11 | A2 | 3 h |
| M2 | accounts, deploy scripts, OPS, REF and bronze DDL, ingestion, registry, run lock | 2, 4, 10 | A3, A11, A13 | 2.5 h |
| M3 | silver, gold, as_of state and rewind; refactor db/legacy into pkg_silver and pkg_gold, then delete db/legacy | 5, 6, 10 | A4, A6, A12 | 3.5 h |
| M4 | RWA, parameters, golden set, views, exports | 7, 8 | A5 | 2 h |
| M5 | security, access-check | 2, 9 | A7, A8 | 3 h |
| M6 | CI db job, README, architecture, runbook, ADRs, NFR | 11 to 14 | A1, A9, A14 | 2 h |

Total about 17.5 h, F12 excluded. db/legacy holds existing PL/SQL to reuse where it meets the constraints; if empty, build from scratch.

## 16. Checks before coding (a failed check: stop and report, no workaround)
- V1 (M0): 23.26.1-faststart runs initdb scripts on first start and passes the compose environment to .sh scripts; VPD, Redaction, FGA, interval partitioning and local bitmap indexes available. If faststart skips initdb, use 23.26.1.
- V2 (M0): utPLSQL v3.2.3 headless install on 23.26.1; utPLSQL-cli version and Java requirement.
- V3 (M0): sqlfluff oracle dialect parses .pks and .pkb; if not, exclude them in .sqlfluff and rely on the deploy compile gate.
- V4 (M2): direct_path_load into a table of another schema, interval-partitioned on load_id: privileges beyond INSERT, error behaviour, partition creation on load, column types (VARCHAR2, NUMBER, TIMESTAMP WITH TIME ZONE), Polars input through the Arrow PyCapsule interface, else pyarrow. If the partitioned load fails, bronze stays a heap table.
- V5 (M4): fetch_df_all(fetch_decimals=True) keeps Decimal through Polars into Parquet.
- V6 (M5): AFTER LOGON ON DATABASE trigger owned by schema-only SRDWH_SEC: privileges required for owner or creator.
- V7 (M5): the §9 redaction expression is accepted; PARTIAL format for a 20-char LEI; under SRDWH_ETL, pkg_gold reading GLD_DIM_COUNTERPARTY raises no ORA-28081.
- V8 (M5): FGA audit_condition with NOT IN accepted; UNIFIED_AUDIT_TRAIL.FGA_POLICY_NAME filled; AUDITOR reads it through AUDIT_VIEWER.

## 17. F12 Real retail feed (optional, after M6, only when requested)
- Source: the Bondora public loan dataset (EUR retail loans). The owner downloads it; its licence is unstated, so the data is never committed and ci keeps the simulator.
- srdwh import-bondora maps loans to the feed contract into data/landing; F2 onward is unchanged. It runs in its own environment: make reset, import, srdwh run --profile bondora.
- Mapping: cpty_id and exposure_id from LoanId, pseudonymised cpty_name, segment RETAIL, rating NR, no LEI, product LOAN, drawn_amt = principal balance, undrawn 0, no collateral, currency EUR, default_flag Y when default_date <= as_of. One as_of per snapshot, its month-end.
- Data minimisation: only loan fields are read; borrower attributes never leave the source file.
- V9 before coding: the dataset is reachable and its field names match the mapping.
