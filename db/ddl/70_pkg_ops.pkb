ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY pkg_ops AS
    c_run_lock_id CONSTANT PLS_INTEGER := 7310001;
    c_stats_tables CONSTANT VARCHAR2(200) := ',SLV_COUNTERPARTY,SLV_EXPOSURE,SLV_REJ_COUNTERPARTY,SLV_REJ_EXPOSURE,'
        || 'GLD_DIM_COUNTERPARTY,GLD_FACT_EXPOSURE,GLD_FACT_RWA,GLD_MART_RWA,';

    PROCEDURE lock_run IS
        l_status INTEGER;
    BEGIN
        l_status := dbms_lock.request(
            id => c_run_lock_id, lockmode => dbms_lock.x_mode, timeout => 0, release_on_commit => FALSE
        );
        IF l_status = 1 THEN
            raise_application_error(c_lock_busy, 'run lock held by another session');
        ELSIF l_status NOT IN (0, 4) THEN
            raise_application_error(c_lock_failed, 'run lock request failed with status ' || l_status);
        END IF;
    END lock_run;

    FUNCTION start_run RETURN NUMBER IS
    BEGIN
        RETURN ops_run_seq.nextval;
    END start_run;

    PROCEDURE fail_orphan_loads(p_run_id IN NUMBER) IS -- F8
    BEGIN
        UPDATE ops_load_registry
        SET
            status = 'FAILED',
            ended_at = systimestamp AT TIME ZONE '+00:00',
            message = 'left STARTED by an interrupted run'
        WHERE status = 'STARTED';
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'fail_orphan_loads');
                RAISE;
    END fail_orphan_loads;

    FUNCTION register_load(
        p_run_id IN NUMBER,
        p_feed IN VARCHAR2,
        p_as_of_date IN DATE,
        p_file_path IN VARCHAR2,
        p_sha256 IN VARCHAR2,
        p_rows_expected IN NUMBER
    ) RETURN NUMBER IS
        l_load_id ops_load_registry.load_id%TYPE;
    BEGIN
        INSERT INTO ops_load_registry (feed, as_of_date, file_path, sha256, rows_expected, status, started_at)
        VALUES (
            p_feed, p_as_of_date, p_file_path, p_sha256, p_rows_expected, 'STARTED', systimestamp AT TIME ZONE '+00:00'
        )
        RETURNING load_id INTO l_load_id;
        RETURN l_load_id;
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'register_load');
                RAISE;
    END register_load;

    FUNCTION is_loaded(p_feed IN VARCHAR2, p_as_of_date IN DATE, p_sha256 IN VARCHAR2) RETURN NUMBER IS -- F2
        l_loaded NUMBER;
    BEGIN
        SELECT count(*) INTO l_loaded
        FROM ops_load_registry
        WHERE
            feed = p_feed AND as_of_date = p_as_of_date AND sha256 = p_sha256 AND status = 'LOADED'
            AND ROWNUM = 1;
        RETURN l_loaded;
    END is_loaded;

    PROCEDURE close_load(p_run_id IN NUMBER, p_load_id IN NUMBER) IS -- F2
        l_rows ops_load_registry.rows_loaded%TYPE;
    BEGIN
        SELECT count(*) INTO l_rows
        FROM (
            SELECT load_id FROM brz_counterparty
            WHERE load_id = p_load_id
            UNION ALL
            SELECT load_id FROM brz_exposure
            WHERE load_id = p_load_id
        ) loaded;
        UPDATE ops_load_registry r
        SET
            r.rows_loaded = l_rows,
            r.status = CASE WHEN l_rows = r.rows_expected THEN 'LOADED' ELSE 'FAILED' END,
            r.message = CASE
                WHEN l_rows != r.rows_expected
                    THEN 'bronze holds ' || l_rows || ' rows, manifest announces ' || r.rows_expected
            END,
            r.ended_at = systimestamp AT TIME ZONE '+00:00'
        WHERE r.load_id = p_load_id AND r.status = 'STARTED';
        IF SQL%ROWCOUNT = 0 THEN
            raise_application_error(c_no_started_load, 'load ' || p_load_id || ' is not STARTED');
        END IF;
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'close_load');
                RAISE;
    END close_load;

    PROCEDURE fail_load(p_run_id IN NUMBER, p_load_id IN NUMBER, p_message IN VARCHAR2) IS
    BEGIN
        UPDATE ops_load_registry
        SET status = 'FAILED', ended_at = systimestamp AT TIME ZONE '+00:00', message = substr(p_message, 1, 4000)
        WHERE load_id = p_load_id AND status = 'STARTED';
        IF SQL%ROWCOUNT = 0 THEN
            raise_application_error(c_no_started_load, 'load ' || p_load_id || ' is not STARTED');
        END IF;
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'fail_load');
                RAISE;
    END fail_load;

    FUNCTION silver_plan(p_rebuild_from IN DATE) RETURN SYS_REFCURSOR IS -- F8
        l_plan SYS_REFCURSOR;
    BEGIN
        OPEN l_plan FOR
            WITH latest AS (
                SELECT
                    as_of_date,
                    max(CASE WHEN feed = 'counterparty' THEN load_id END) AS cpty_load_id,
                    max(CASE WHEN feed = 'exposure' THEN load_id END) AS expo_load_id
                FROM ops_load_registry
                WHERE status = 'LOADED'
                GROUP BY as_of_date
            )

            SELECT
                l.as_of_date,
                l.cpty_load_id,
                l.expo_load_id
            FROM latest l
            LEFT JOIN ops_asof_state s ON l.as_of_date = s.as_of_date
            WHERE
                s.as_of_date IS NULL
                OR decode(s.slv_cpty_load_id, l.cpty_load_id, 0, 1) = 1
                OR decode(s.slv_expo_load_id, l.expo_load_id, 0, 1) = 1
                OR l.as_of_date >= p_rebuild_from
            ORDER BY l.as_of_date;
        RETURN l_plan;
    END silver_plan;

    PROCEDURE record_silver(
        p_run_id IN NUMBER, p_as_of_date IN DATE, p_cpty_load_id IN NUMBER, p_expo_load_id IN NUMBER
    ) IS
    BEGIN
        MERGE INTO ops_asof_state s
        USING (SELECT p_as_of_date AS as_of_date FROM dual) d
        ON (s.as_of_date = d.as_of_date)
        WHEN MATCHED THEN UPDATE SET
            s.slv_cpty_load_id = p_cpty_load_id,
            s.slv_expo_load_id = p_expo_load_id,
            s.slv_at = systimestamp AT TIME ZONE '+00:00'
        WHEN NOT MATCHED THEN INSERT (as_of_date, slv_cpty_load_id, slv_expo_load_id, slv_at)
            VALUES (d.as_of_date, p_cpty_load_id, p_expo_load_id, systimestamp AT TIME ZONE '+00:00');
    EXCEPTION
        WHEN OTHERS THEN
            pkg_err.log_error(p_run_id, 'record_silver');
            RAISE;
    END record_silver;

    FUNCTION gold_start(p_rebuild_from IN DATE) RETURN DATE IS -- F8
        l_start DATE;
    BEGIN
        SELECT min(as_of_date) INTO l_start
        FROM ops_asof_state
        WHERE
            gld_cpty_load_id IS NULL
            OR gld_cpty_load_id != slv_cpty_load_id
            OR gld_expo_load_id != slv_expo_load_id
            OR as_of_date >= p_rebuild_from;
        RETURN l_start;
    END gold_start;

    FUNCTION gold_built_until RETURN DATE IS
        l_until DATE;
    BEGIN
        SELECT max(as_of_date) INTO l_until
        FROM ops_asof_state
        WHERE gld_cpty_load_id IS NOT NULL;
        RETURN l_until;
    END gold_built_until;

    FUNCTION gold_dates(p_from IN DATE) RETURN SYS_REFCURSOR IS
        l_dates SYS_REFCURSOR;
    BEGIN
        OPEN l_dates FOR
            SELECT as_of_date
            FROM ops_asof_state
            WHERE as_of_date >= p_from
            ORDER BY as_of_date;
        RETURN l_dates;
    END gold_dates;

    PROCEDURE clear_gold(p_run_id IN NUMBER, p_from IN DATE) IS
    BEGIN
        UPDATE ops_asof_state
        SET
            gld_cpty_load_id = NULL,
            gld_expo_load_id = NULL,
            gld_at = NULL
        WHERE as_of_date >= p_from;
    EXCEPTION
        WHEN OTHERS THEN
            pkg_err.log_error(p_run_id, 'clear_gold');
            RAISE;
    END clear_gold;

    PROCEDURE record_gold(p_run_id IN NUMBER, p_as_of_date IN DATE) IS
    BEGIN
        UPDATE ops_asof_state
        SET
            gld_cpty_load_id = slv_cpty_load_id,
            gld_expo_load_id = slv_expo_load_id,
            gld_at = systimestamp AT TIME ZONE '+00:00'
        WHERE as_of_date = p_as_of_date;
    EXCEPTION
        WHEN OTHERS THEN
            pkg_err.log_error(p_run_id, 'record_gold');
            RAISE;
    END record_gold;

    PROCEDURE gather_stats(p_run_id IN NUMBER, p_table IN VARCHAR2) IS -- F4
    BEGIN
        IF instr(c_stats_tables, ',' || upper(p_table) || ',') = 0 THEN
            raise_application_error(c_unknown_table, 'statistics refused for ' || p_table);
        END IF;
        dbms_stats.gather_table_stats(ownname => 'SRDWH_OWNER', tabname => upper(p_table));
    EXCEPTION
        WHEN OTHERS THEN
            pkg_err.log_error(p_run_id, 'gather_stats');
            RAISE;
    END gather_stats;

    PROCEDURE log_step(
        p_run_id IN NUMBER,
        p_step IN VARCHAR2,
        p_as_of_date IN DATE,
        p_duration_ms IN NUMBER,
        p_rows_in IN NUMBER,
        p_rows_out IN NUMBER,
        p_rows_rejected IN NUMBER,
        p_status IN VARCHAR2,
        p_message IN VARCHAR2
    ) IS
        l_ended TIMESTAMP WITH TIME ZONE := systimestamp AT TIME ZONE '+00:00';
    BEGIN
        INSERT INTO ops_run_log (
            run_id, step, as_of_date, started_at, ended_at, rows_in, rows_out, rows_rejected, status, message
        )
        VALUES (
            p_run_id, p_step, p_as_of_date, l_ended - numtodsinterval(p_duration_ms / 1000, 'SECOND'), l_ended,
            p_rows_in, p_rows_out, p_rows_rejected, p_status, substr(p_message, 1, 4000)
        );
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'log_step');
                RAISE;
    END log_step;
END pkg_ops;
/
