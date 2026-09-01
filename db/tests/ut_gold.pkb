ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY ut_gold AS
    c_jan CONSTANT DATE := DATE '2001-01-31';
    c_feb CONSTANT DATE := DATE '2001-02-28';
    c_mar CONSTANT DATE := DATE '2001-03-31';

    PROCEDURE load(p_as_of IN DATE) IS
    BEGIN
        pkg_gold.load_counterparties(NULL, p_as_of);
    END load;

    FUNCTION versions(p_cpty_id IN VARCHAR2) RETURN NUMBER IS
        l_versions NUMBER;
    BEGIN
        SELECT count(*) INTO l_versions
        FROM gld_dim_counterparty
        WHERE cpty_id = p_cpty_id;
        RETURN l_versions;
    END versions;

    PROCEDURE history IS
    BEGIN
        ut_data.add_counterparty(c_jan, 'UTG1');
        ut_data.add_counterparty(c_jan, 'UTG2');
        ut_data.add_counterparty(c_jan, 'UTG3', p_default => 'Y');
        load(c_jan);
        ut_data.add_counterparty(c_feb, 'UTG1', p_rating => 'BB');
        ut_data.add_counterparty(c_feb, 'UTG3');
        load(c_feb);
        ut_data.add_counterparty(c_mar, 'UTG1', p_rating => 'B');
        ut_data.add_counterparty(c_mar, 'UTG2', p_rating => 'A');
        ut_data.add_counterparty(c_mar, 'UTG3');
        load(c_mar);
    END history;

    PROCEDURE scd2_new_version_on_change IS
        l_closed gld_dim_counterparty%ROWTYPE;
        l_open gld_dim_counterparty%ROWTYPE;
    BEGIN
        ut_data.add_counterparty(c_jan, 'UTG1');
        load(c_jan);
        ut_data.add_counterparty(c_feb, 'UTG1', p_rating => 'BB');
        load(c_feb);
        SELECT * INTO l_closed
        FROM gld_dim_counterparty
        WHERE cpty_id = 'UTG1' AND valid_from = c_jan;
        SELECT * INTO l_open
        FROM gld_dim_counterparty
        WHERE cpty_id = 'UTG1' AND valid_from = c_feb;
        ut.expect(versions('UTG1')).to_equal(2);
        ut.expect(l_closed.valid_to).to_equal(c_feb);
        ut.expect(l_closed.is_current).to_equal('N');
        ut.expect(l_closed.rating).to_equal('BBB');
        ut.expect(l_open.valid_to).to_equal(pkg_gold.c_open_end);
        ut.expect(l_open.is_current).to_equal('Y');
        ut.expect(l_open.rating).to_equal('BB');
    END scd2_new_version_on_change;

    PROCEDURE scd1_overwrites_all_versions IS
        l_names NUMBER;
    BEGIN
        ut_data.add_counterparty(c_jan, 'UTG1', p_name => 'Old Name SA');
        load(c_jan);
        ut_data.add_counterparty(c_feb, 'UTG1', p_rating => 'BB', p_name => 'Old Name SA');
        load(c_feb);
        ut_data.add_counterparty(c_mar, 'UTG1', p_rating => 'BB', p_name => 'New Name SA');
        load(c_mar);
        SELECT count(*) INTO l_names
        FROM gld_dim_counterparty
        WHERE cpty_id = 'UTG1' AND cpty_name = 'New Name SA';
        ut.expect(versions('UTG1')).to_equal(2);
        ut.expect(l_names).to_equal(2);
    END scd1_overwrites_all_versions;

    PROCEDURE missing_counterparty_keeps_version IS
        l_kept gld_dim_counterparty%ROWTYPE;
    BEGIN
        ut_data.add_counterparty(c_jan, 'UTG1');
        ut_data.add_counterparty(c_jan, 'UTG2');
        load(c_jan);
        ut_data.add_counterparty(c_feb, 'UTG1', p_rating => 'BB');
        load(c_feb);
        SELECT * INTO l_kept
        FROM gld_dim_counterparty
        WHERE cpty_id = 'UTG2';
        ut.expect(l_kept.valid_from).to_equal(c_jan);
        ut.expect(l_kept.valid_to).to_equal(pkg_gold.c_open_end);
        ut.expect(l_kept.is_current).to_equal('Y');
    END missing_counterparty_keeps_version;

    PROCEDURE no_overlapping_versions IS
        l_overlaps NUMBER;
    BEGIN
        history;
        SELECT count(*) INTO l_overlaps
        FROM gld_dim_counterparty a
        INNER JOIN gld_dim_counterparty b
            ON a.cpty_id = b.cpty_id AND a.cpty_sk < b.cpty_sk
        WHERE a.valid_from < b.valid_to AND b.valid_from < a.valid_to;
        ut.expect(l_overlaps).to_equal(0);
    END no_overlapping_versions;

    PROCEDURE one_current_version IS
        l_wrong NUMBER;
    BEGIN
        history;
        SELECT count(*) INTO l_wrong
        FROM (
            SELECT cpty_id
            FROM gld_dim_counterparty
            GROUP BY cpty_id
            HAVING sum(CASE WHEN is_current = 'Y' THEN 1 ELSE 0 END) != 1
        );
        ut.expect(l_wrong).to_equal(0);
        ut.expect(versions('UTG1')).to_equal(3);
        ut.expect(versions('UTG3')).to_equal(2);
    END one_current_version;

    PROCEDURE contiguous_versions IS
        l_gaps NUMBER;
    BEGIN
        history;
        SELECT count(*) INTO l_gaps
        FROM (
            SELECT
                valid_to,
                lead(valid_from) OVER (PARTITION BY cpty_id ORDER BY valid_from) AS next_from
            FROM gld_dim_counterparty
        )
        WHERE next_from IS NOT NULL AND valid_to != next_from;
        ut.expect(l_gaps).to_equal(0);
    END contiguous_versions;

    PROCEDURE fact_history IS
    BEGIN
        ut_data.add_counterparty(c_jan, 'UTG1');
        ut_data.add_counterparty(c_jan, 'UTG2');
        ut_data.add_exposure(c_jan, 'UTGE1', 'UTG1');
        ut_data.add_exposure(c_jan, 'UTGE2', 'UTG2');
        ut_data.build(c_jan);
        ut_data.add_counterparty(c_feb, 'UTG1', p_rating => 'BB');
        ut_data.add_counterparty(c_feb, 'UTG2');
        ut_data.add_exposure(c_feb, 'UTGE1', 'UTG1');
        ut_data.add_exposure(c_feb, 'UTGE2', 'UTG2');
        ut_data.build(c_feb);
        ut_data.add_counterparty(c_mar, 'UTG1', p_rating => 'B');
        ut_data.add_exposure(c_mar, 'UTGE1', 'UTG1');
        ut_data.build(c_mar);
    END fact_history;

    PROCEDURE fact_grain_unique IS
        l_rows NUMBER;
        l_keys NUMBER;
    BEGIN
        fact_history;
        ut_data.build(c_mar);
        SELECT count(*), count(DISTINCT exposure_id || '|' || as_of_date) INTO l_rows, l_keys
        FROM gld_fact_exposure
        WHERE exposure_id LIKE 'UTGE%';
        ut.expect(l_rows).to_equal(5);
        ut.expect(l_keys).to_equal(l_rows);
    END fact_grain_unique;

    PROCEDURE fact_on_valid_version IS
        l_wrong NUMBER;
    BEGIN
        fact_history;
        SELECT count(*) INTO l_wrong
        FROM gld_fact_exposure f
        INNER JOIN gld_dim_counterparty c ON f.cpty_sk = c.cpty_sk
        WHERE NOT (f.as_of_date >= c.valid_from AND f.as_of_date < c.valid_to);
        ut.expect(l_wrong).to_equal(0);
    END fact_on_valid_version;

    PROCEDURE counts_silver_fact_rwa IS
        l_wrong NUMBER;
    BEGIN
        fact_history;
        SELECT count(*) INTO l_wrong
        FROM (
            SELECT as_of_date, count(*) AS silver_rows
            FROM slv_exposure
            GROUP BY as_of_date
        ) s
        LEFT JOIN (
            SELECT as_of_date, count(*) AS fact_rows
            FROM gld_fact_exposure
            GROUP BY as_of_date
        ) f ON s.as_of_date = f.as_of_date
        LEFT JOIN (
            SELECT as_of_date, count(*) AS rwa_rows
            FROM gld_fact_rwa
            GROUP BY as_of_date
        ) r ON s.as_of_date = r.as_of_date
        WHERE
            s.as_of_date IN (c_jan, c_feb, c_mar)
            AND (decode(s.silver_rows, f.fact_rows, 0, 1) = 1 OR decode(s.silver_rows, r.rwa_rows, 0, 1) = 1);
        ut.expect(l_wrong).to_equal(0);
    END counts_silver_fact_rwa;

    PROCEDURE segment_matches_version IS
        l_wrong NUMBER;
    BEGIN
        fact_history;
        SELECT count(*) INTO l_wrong
        FROM gld_fact_exposure f
        INNER JOIN gld_dim_counterparty c ON f.cpty_sk = c.cpty_sk
        WHERE f.segment_code != c.segment_code;
        ut.expect(l_wrong).to_equal(0);
    END segment_matches_version;

    PROCEDURE rewind_reopens_versions IS
        l_reopened gld_dim_counterparty%ROWTYPE;
        l_facts NUMBER;
    BEGIN
        fact_history;
        pkg_gold.rewind(NULL, c_feb);
        SELECT * INTO l_reopened
        FROM gld_dim_counterparty
        WHERE cpty_id = 'UTG1';
        SELECT count(*) INTO l_facts
        FROM gld_fact_exposure
        WHERE as_of_date >= c_feb;
        ut.expect(versions('UTG1')).to_equal(1);
        ut.expect(l_reopened.valid_from).to_equal(c_jan);
        ut.expect(l_reopened.valid_to).to_equal(pkg_gold.c_open_end);
        ut.expect(l_reopened.is_current).to_equal('Y');
        ut.expect(l_facts).to_equal(0);
    END rewind_reopens_versions;
END ut_gold;
/
