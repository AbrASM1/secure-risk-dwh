ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY ut_ops AS
    c_sha CONSTANT VARCHAR2(64) := rpad('a', 64, 'a');
    c_other_sha CONSTANT VARCHAR2(64) := rpad('b', 64, 'b');
    c_as_of CONSTANT DATE := DATE '2001-01-31';

    PROCEDURE add_load(p_feed IN VARCHAR2, p_sha256 IN VARCHAR2, p_status IN VARCHAR2) IS
    BEGIN
        INSERT INTO ops_load_registry (feed, as_of_date, file_path, sha256, rows_expected, status, started_at)
        VALUES (p_feed, c_as_of, 'probe', p_sha256, 0, p_status, systimestamp AT TIME ZONE 'UTC');
    END add_load;

    PROCEDURE skip_loaded_same_sha256 IS
    BEGIN
        add_load('counterparty', c_sha, 'LOADED');
        ut.expect(pkg_ops.is_loaded('counterparty', c_as_of, c_sha)).to_equal(1);
        ut.expect(pkg_ops.is_loaded('counterparty', c_as_of, c_other_sha)).to_equal(0);
        ut.expect(pkg_ops.is_loaded('exposure', c_as_of, c_sha)).to_equal(0);
        ut.expect(pkg_ops.is_loaded('counterparty', c_as_of + 1, c_sha)).to_equal(0);
    END skip_loaded_same_sha256;

    PROCEDURE failed_load_not_loaded IS
    BEGIN
        add_load('exposure', c_sha, 'FAILED');
        add_load('exposure', c_sha, 'STARTED');
        ut.expect(pkg_ops.is_loaded('exposure', c_as_of, c_sha)).to_equal(0);
    END failed_load_not_loaded;
END ut_ops;
/
