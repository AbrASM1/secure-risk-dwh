ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY ut_ops AS
    c_sha CONSTANT VARCHAR2(64) := rpad('a', 64, 'a');
    c_other_sha CONSTANT VARCHAR2(64) := rpad('b', 64, 'b');
    c_as_of CONSTANT DATE := DATE '2001-01-31';

    PROCEDURE add_load(p_feed IN VARCHAR2, p_sha256 IN VARCHAR2, p_status IN VARCHAR2) IS
    BEGIN
        INSERT INTO ops_load_registry (feed, as_of_date, file_path, sha256, rows_expected, status, started_at)
        VALUES (p_feed, c_as_of, 'probe', p_sha256, 0, p_status, systimestamp AT TIME ZONE '+00:00');
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

    FUNCTION new_load(p_feed IN VARCHAR2, p_as_of IN DATE) RETURN NUMBER IS
        l_load_id ops_load_registry.load_id%TYPE;
    BEGIN
        INSERT INTO ops_load_registry (feed, as_of_date, file_path, sha256, rows_expected, status, started_at)
        VALUES (p_feed, p_as_of, 'probe', c_sha, 0, 'LOADED', systimestamp AT TIME ZONE '+00:00')
        RETURNING load_id INTO l_load_id;
        RETURN l_load_id;
    END new_load;

    PROCEDURE add_state(p_as_of IN DATE, p_gold IN VARCHAR2) IS
        l_cpty NUMBER := new_load('counterparty', p_as_of);
        l_expo NUMBER := new_load('exposure', p_as_of);
        l_newer NUMBER := new_load('exposure', p_as_of);
    BEGIN
        INSERT INTO ops_asof_state (
            as_of_date, slv_cpty_load_id, slv_expo_load_id, gld_cpty_load_id, gld_expo_load_id, slv_at, gld_at
        )
        VALUES (
            p_as_of, l_cpty, l_expo,
            CASE p_gold WHEN 'clean' THEN l_cpty WHEN 'stale' THEN l_cpty END,
            CASE p_gold WHEN 'clean' THEN l_expo WHEN 'stale' THEN l_newer END,
            systimestamp,
            CASE WHEN p_gold IN ('clean', 'stale') THEN systimestamp END
        );
    END add_state;

    PROCEDURE dirty_asof_detection IS
    BEGIN
        add_state(DATE '2001-01-31', 'clean');
        add_state(DATE '2001-02-28', 'stale');
        add_state(DATE '2001-03-31', 'empty');
        ut.expect(pkg_ops.gold_start(NULL)).to_equal(DATE '2001-02-28');
        ut.expect(pkg_ops.gold_start(DATE '2001-01-31')).to_equal(DATE '2001-01-31');
        ut.expect(pkg_ops.gold_built_until).to_be_not_null();
    END dirty_asof_detection;

    PROCEDURE gather_stats_rejects_unknown_table IS
    BEGIN
        pkg_ops.gather_stats(NULL, 'OPS_LOAD_REGISTRY');
    END gather_stats_rejects_unknown_table;
END ut_ops;
/
