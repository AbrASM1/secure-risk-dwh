ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;

CREATE TABLE ops_load_registry (
    load_id NUMBER(18) GENERATED ALWAYS AS IDENTITY,
    feed VARCHAR2(20) NOT NULL,
    as_of_date DATE NOT NULL,
    file_path VARCHAR2(1000) NOT NULL,
    sha256 VARCHAR2(64) NOT NULL,
    rows_expected NUMBER(10) NOT NULL,
    rows_loaded NUMBER(10),
    rows_rejected NUMBER(10),
    status VARCHAR2(10) NOT NULL,
    started_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    ended_at TIMESTAMP(6) WITH TIME ZONE,
    message VARCHAR2(4000),
    CONSTRAINT ops_load_registry_pk PRIMARY KEY (load_id),
    CONSTRAINT ops_load_registry_feed_ck CHECK (feed IN ('counterparty', 'exposure')),
    CONSTRAINT ops_load_registry_status_ck CHECK (status IN ('STARTED', 'LOADED', 'FAILED'))
);

COMMENT ON TABLE ops_load_registry IS 'One row per attempt to load a landing file into bronze (F2).';
COMMENT ON COLUMN ops_load_registry.load_id IS 'Load identifier.';
COMMENT ON COLUMN ops_load_registry.feed IS 'Feed of the file.';
COMMENT ON COLUMN ops_load_registry.as_of_date IS 'As-of date of the file partition.';
COMMENT ON COLUMN ops_load_registry.file_path IS 'Landing file path relative to data/landing.';
COMMENT ON COLUMN ops_load_registry.sha256 IS 'SHA-256 of the file, checked against the manifest.';
COMMENT ON COLUMN ops_load_registry.rows_expected IS 'Row count announced by the manifest.';
COMMENT ON COLUMN ops_load_registry.rows_loaded IS 'Rows found in bronze for this load_id once the load ended.';
COMMENT ON COLUMN ops_load_registry.rows_rejected
IS 'Rows rejected by the silver rules, set in phase 1a; reject rate = rows_rejected / rows_loaded.';
COMMENT ON COLUMN ops_load_registry.status IS 'STARTED, then LOADED or FAILED.';
COMMENT ON COLUMN ops_load_registry.started_at IS 'Start of the attempt, UTC.';
COMMENT ON COLUMN ops_load_registry.ended_at IS 'End of the attempt, UTC.';
COMMENT ON COLUMN ops_load_registry.message IS 'Failure reason.';

CREATE TABLE ops_asof_state (
    as_of_date DATE NOT NULL,
    slv_cpty_load_id NUMBER(18) NOT NULL,
    slv_expo_load_id NUMBER(18) NOT NULL,
    gld_cpty_load_id NUMBER(18),
    gld_expo_load_id NUMBER(18),
    slv_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    gld_at TIMESTAMP(6) WITH TIME ZONE,
    CONSTRAINT ops_asof_state_pk PRIMARY KEY (as_of_date),
    CONSTRAINT ops_asof_state_gold_ck CHECK (
        (gld_cpty_load_id IS NULL AND gld_expo_load_id IS NULL AND gld_at IS NULL)
        OR (gld_cpty_load_id IS NOT NULL AND gld_expo_load_id IS NOT NULL AND gld_at IS NOT NULL)
    ),
    CONSTRAINT ops_asof_state_slv_cpty_load_id_fk FOREIGN KEY (slv_cpty_load_id) REFERENCES ops_load_registry (load_id),
    CONSTRAINT ops_asof_state_slv_expo_load_id_fk FOREIGN KEY (slv_expo_load_id) REFERENCES ops_load_registry (load_id),
    CONSTRAINT ops_asof_state_gld_cpty_load_id_fk FOREIGN KEY (gld_cpty_load_id) REFERENCES ops_load_registry (load_id),
    CONSTRAINT ops_asof_state_gld_expo_load_id_fk FOREIGN KEY (gld_expo_load_id) REFERENCES ops_load_registry (load_id)
);

COMMENT ON TABLE ops_asof_state IS 'Loads in silver and in gold for each as_of; the next run resumes from it (F8).';
COMMENT ON COLUMN ops_asof_state.as_of_date IS 'As-of date.';
COMMENT ON COLUMN ops_asof_state.slv_cpty_load_id IS 'Counterparty load in silver.';
COMMENT ON COLUMN ops_asof_state.slv_expo_load_id IS 'Exposure load in silver.';
COMMENT ON COLUMN ops_asof_state.gld_cpty_load_id
IS 'Counterparty load in gold, empty while gold is absent or rewound.';
COMMENT ON COLUMN ops_asof_state.gld_expo_load_id IS 'Exposure load in gold, empty while gold is absent or rewound.';
COMMENT ON COLUMN ops_asof_state.slv_at IS 'Time silver was replaced, UTC.';
COMMENT ON COLUMN ops_asof_state.gld_at IS 'Time gold and exports were completed, UTC.';

CREATE TABLE ops_run_log (
    log_id NUMBER(18) GENERATED ALWAYS AS IDENTITY,
    run_id NUMBER(18) NOT NULL,
    step VARCHAR2(30) NOT NULL,
    as_of_date DATE,
    started_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    ended_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    rows_in NUMBER(10),
    rows_out NUMBER(10),
    rows_rejected NUMBER(10),
    status VARCHAR2(10) NOT NULL,
    message VARCHAR2(4000),
    CONSTRAINT ops_run_log_pk PRIMARY KEY (log_id),
    CONSTRAINT ops_run_log_status_ck CHECK (status IN ('OK', 'FAILED', 'BREACH'))
);

COMMENT ON TABLE ops_run_log IS 'One row per run step and as_of (F8).';
COMMENT ON COLUMN ops_run_log.log_id IS 'Log row identifier.';
COMMENT ON COLUMN ops_run_log.run_id IS 'Run identifier from OPS_RUN_SEQ.';
COMMENT ON COLUMN ops_run_log.step IS 'Step name.';
COMMENT ON COLUMN ops_run_log.as_of_date IS 'As-of date of the step, empty for run-wide steps.';
COMMENT ON COLUMN ops_run_log.started_at IS 'Step start, UTC.';
COMMENT ON COLUMN ops_run_log.ended_at IS 'Step end, UTC.';
COMMENT ON COLUMN ops_run_log.rows_in IS 'Rows read.';
COMMENT ON COLUMN ops_run_log.rows_out IS 'Rows written.';
COMMENT ON COLUMN ops_run_log.rows_rejected IS 'Rows rejected.';
COMMENT ON COLUMN ops_run_log.status IS 'OK, FAILED, or BREACH when the reject threshold is exceeded.';
COMMENT ON COLUMN ops_run_log.message IS 'Outcome detail.';

CREATE TABLE ops_err_log (
    err_id NUMBER(18) GENERATED ALWAYS AS IDENTITY,
    run_id NUMBER(18),
    step VARCHAR2(30) NOT NULL,
    sql_code NUMBER(10) NOT NULL,
    message VARCHAR2(4000) NOT NULL,
    backtrace VARCHAR2(4000),
    logged_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    CONSTRAINT ops_err_log_pk PRIMARY KEY (err_id)
);

COMMENT ON TABLE ops_err_log IS 'Errors logged by pkg_err in an autonomous transaction before re-raising (F8).';
COMMENT ON COLUMN ops_err_log.err_id IS 'Error row identifier.';
COMMENT ON COLUMN ops_err_log.run_id IS 'Run identifier, empty for errors outside a run such as the logon trigger.';
COMMENT ON COLUMN ops_err_log.step IS 'Step or component that raised.';
COMMENT ON COLUMN ops_err_log.sql_code IS 'SQLCODE of the error.';
COMMENT ON COLUMN ops_err_log.message IS 'Error message.';
COMMENT ON COLUMN ops_err_log.backtrace IS 'DBMS_UTILITY.FORMAT_ERROR_BACKTRACE.';
COMMENT ON COLUMN ops_err_log.logged_at IS 'Time of logging, UTC.';

CREATE SEQUENCE ops_run_seq;
