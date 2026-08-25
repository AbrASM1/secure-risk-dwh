ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE pkg_ops AUTHID DEFINER AS
    c_lock_busy CONSTANT PLS_INTEGER := -20101;
    c_lock_failed CONSTANT PLS_INTEGER := -20102;
    c_no_started_load CONSTANT PLS_INTEGER := -20103;
    c_unknown_table CONSTANT PLS_INTEGER := -20104;

    procedure LOCK_RUN;

    FUNCTION start_run RETURN NUMBER;

    PROCEDURE fail_orphan_loads(p_run_id IN NUMBER);

    FUNCTION register_load(
        p_run_id IN NUMBER,
        p_feed IN VARCHAR2,
        p_as_of_date IN DATE,
        p_file_path IN VARCHAR2,
        p_sha256 IN VARCHAR2,
        p_rows_expected IN NUMBER
    ) RETURN NUMBER;

    FUNCTION is_loaded(p_feed IN VARCHAR2, p_as_of_date IN DATE, p_sha256 IN VARCHAR2) RETURN NUMBER;

    PROCEDURE close_load(p_run_id IN NUMBER, p_load_id IN NUMBER);

    PROCEDURE fail_load(p_run_id IN NUMBER, p_load_id IN NUMBER, p_message IN VARCHAR2);

    FUNCTION silver_plan(p_rebuild_from IN DATE) RETURN SYS_REFCURSOR;

    PROCEDURE record_silver(
        p_run_id IN NUMBER, p_as_of_date IN DATE, p_cpty_load_id IN NUMBER, p_expo_load_id IN NUMBER
    );

    FUNCTION gold_start(p_rebuild_from IN DATE) RETURN DATE;

    FUNCTION gold_built_until RETURN DATE;

    FUNCTION gold_dates(p_from IN DATE) RETURN SYS_REFCURSOR;

    PROCEDURE clear_gold(p_run_id IN NUMBER, p_from IN DATE);

    PROCEDURE record_gold(p_run_id IN NUMBER, p_as_of_date IN DATE);

    PROCEDURE gather_stats(p_run_id IN NUMBER, p_table IN VARCHAR2);

    PROCEDURE log_step(
        p_run_id IN NUMBER,
        p_step IN VARCHAR2,
        p_as_of_date IN DATE,
        p_started_at IN TIMESTAMP WITH TIME ZONE,
        p_rows_in IN NUMBER,
        p_rows_out IN NUMBER,
        p_rows_rejected IN NUMBER,
        p_status IN VARCHAR2,
        p_message IN VARCHAR2
    );
END pkg_ops;
/
