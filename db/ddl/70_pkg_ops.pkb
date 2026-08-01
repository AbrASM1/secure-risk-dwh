ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY pkg_ops AS
    c_run_lock_id CONSTANT PLS_INTEGER := 7310001;

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
            ended_at = systimestamp AT TIME ZONE 'UTC',
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
            p_feed, p_as_of_date, p_file_path, p_sha256, p_rows_expected, 'STARTED', systimestamp AT TIME ZONE 'UTC'
        )
        RETURNING load_id INTO l_load_id;
        RETURN l_load_id;
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'register_load');
                RAISE;
    END register_load;

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
            r.ended_at = systimestamp AT TIME ZONE 'UTC'
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
        SET status = 'FAILED', ended_at = systimestamp AT TIME ZONE 'UTC', message = substr(p_message, 1, 4000)
        WHERE load_id = p_load_id AND status = 'STARTED';
        IF SQL%ROWCOUNT = 0 THEN
            raise_application_error(c_no_started_load, 'load ' || p_load_id || ' is not STARTED');
        END IF;
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'fail_load');
                RAISE;
    END fail_load;

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
    ) IS
    BEGIN
        INSERT INTO ops_run_log (
            run_id, step, as_of_date, started_at, ended_at, rows_in, rows_out, rows_rejected, status, message
        )
        VALUES (
            p_run_id, p_step, p_as_of_date, p_started_at, systimestamp AT TIME ZONE 'UTC',
            p_rows_in, p_rows_out, p_rows_rejected, p_status, substr(p_message, 1, 4000)
        );
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'log_step');
                RAISE;
    END log_step;
END pkg_ops;
/
