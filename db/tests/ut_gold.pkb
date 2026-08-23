ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY ut_gold AS
    c_jan CONSTANT DATE := DATE '2001-01-31';
    c_feb CONSTANT DATE := DATE '2001-02-28';
    c_mar CONSTANT DATE := DATE '2001-03-31';

    PROCEDURE add_silver(
        p_as_of IN DATE,
        p_cpty_id IN VARCHAR2,
        p_rating IN VARCHAR2 DEFAULT 'BBB',
        p_name IN VARCHAR2 DEFAULT 'Atlas Foods SA',
        p_default IN VARCHAR2 DEFAULT 'N'
    ) IS
    BEGIN
        INSERT INTO slv_counterparty (
            as_of_date, cpty_id, cpty_name, lei, segment_code, country, rating, default_flag, load_id, src_row
        )
        VALUES (p_as_of, p_cpty_id, p_name, NULL, 'SME', 'FR', p_rating, p_default, 0, 1);
    END add_silver;

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
        add_silver(c_jan, 'UTG1');
        add_silver(c_jan, 'UTG2');
        add_silver(c_jan, 'UTG3', p_default => 'Y');
        load(c_jan);
        add_silver(c_feb, 'UTG1', p_rating => 'BB');
        add_silver(c_feb, 'UTG3');
        load(c_feb);
        add_silver(c_mar, 'UTG1', p_rating => 'B');
        add_silver(c_mar, 'UTG2', p_rating => 'A');
        add_silver(c_mar, 'UTG3');
        load(c_mar);
    END history;

    PROCEDURE scd2_new_version_on_change IS
        l_closed gld_dim_counterparty%ROWTYPE;
        l_open gld_dim_counterparty%ROWTYPE;
    BEGIN
        add_silver(c_jan, 'UTG1');
        load(c_jan);
        add_silver(c_feb, 'UTG1', p_rating => 'BB');
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
        add_silver(c_jan, 'UTG1', p_name => 'Old Name SA');
        load(c_jan);
        add_silver(c_feb, 'UTG1', p_rating => 'BB', p_name => 'Old Name SA');
        load(c_feb);
        add_silver(c_mar, 'UTG1', p_rating => 'BB', p_name => 'New Name SA');
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
        add_silver(c_jan, 'UTG1');
        add_silver(c_jan, 'UTG2');
        load(c_jan);
        add_silver(c_feb, 'UTG1', p_rating => 'BB');
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
END ut_gold;
/
