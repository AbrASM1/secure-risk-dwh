ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY pkg_err AS
    PROCEDURE log_error(p_run_id IN NUMBER, p_step IN VARCHAR2) IS
        PRAGMA AUTONOMOUS_TRANSACTION;
        l_code ops_err_log.sql_code%TYPE := sqlcode;
        l_message ops_err_log.message%TYPE := substr(sqlerrm, 1, 4000);
        l_backtrace ops_err_log.backtrace%TYPE := substr(dbms_utility.format_error_backtrace, 1, 4000);
    BEGIN
        INSERT INTO ops_err_log (run_id, step, sql_code, message, backtrace, logged_at)
        VALUES (p_run_id, substr(p_step, 1, 30), l_code, l_message, l_backtrace, systimestamp AT TIME ZONE 'UTC');
        COMMIT;
    END log_error;
END pkg_err;
/
