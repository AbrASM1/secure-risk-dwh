ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY ut_silver AS
    c_as_of CONSTANT DATE := DATE '2001-01-31';
    g_load_id ops_load_registry.load_id%TYPE;
    g_lei ut_lei_gleif.lei%TYPE;

    PROCEDURE setup IS
    BEGIN
        INSERT INTO ops_load_registry (feed, as_of_date, file_path, sha256, rows_expected, status, started_at)
        VALUES ('counterparty', c_as_of, 'ut_silver', rpad('0', 64, '0'), 0, 'LOADED', systimestamp)
        RETURNING load_id INTO g_load_id;
        SELECT min(lei) INTO g_lei
        FROM ut_lei_gleif;
    END setup;

    FUNCTION pick(
        p_name IN VARCHAR2,
        p_default IN VARCHAR2,
        p_column IN VARCHAR2,
        p_value IN VARCHAR2,
        p_column_2 IN VARCHAR2,
        p_value_2 IN VARCHAR2
    ) RETURN VARCHAR2 IS
    BEGIN
        RETURN CASE p_name WHEN p_column THEN p_value WHEN p_column_2 THEN p_value_2 ELSE p_default END;
    END pick;

    PROCEDURE add_row(
        p_row IN PLS_INTEGER,
        p_column IN VARCHAR2 DEFAULT NULL,
        p_value IN VARCHAR2 DEFAULT NULL,
        p_column_2 IN VARCHAR2 DEFAULT NULL,
        p_value_2 IN VARCHAR2 DEFAULT NULL
    ) IS
        l_cpty_id brz_counterparty.cpty_id%TYPE
            := pick('cpty_id', 'CP' || lpad(p_row, 8, '0'), p_column, p_value, p_column_2, p_value_2);
        l_cpty_name brz_counterparty.cpty_name%TYPE
            := pick('cpty_name', 'Atlas Foods SA', p_column, p_value, p_column_2, p_value_2);
        l_lei brz_counterparty.lei%TYPE := pick('lei', g_lei, p_column, p_value, p_column_2, p_value_2);
        l_segment brz_counterparty.segment_code%TYPE
            := pick('segment_code', 'CORPORATE', p_column, p_value, p_column_2, p_value_2);
        l_country brz_counterparty.country%TYPE := pick('country', 'FR', p_column, p_value, p_column_2, p_value_2);
        l_rating brz_counterparty.rating%TYPE := pick('rating', 'BBB', p_column, p_value, p_column_2, p_value_2);
        l_flag brz_counterparty.default_flag%TYPE
            := pick('default_flag', 'N', p_column, p_value, p_column_2, p_value_2);
        l_date brz_counterparty.as_of_date%TYPE
            := pick('as_of_date', '2001-01-31', p_column, p_value, p_column_2, p_value_2);
    BEGIN
        INSERT INTO brz_counterparty (
            cpty_id, cpty_name, lei, segment_code, country, rating, default_flag, as_of_date,
            load_id, src_file, src_row, ingested_at
        )
        VALUES (
            l_cpty_id, l_cpty_name, l_lei, l_segment, l_country, l_rating, l_flag, l_date,
            g_load_id, 'ut_silver', p_row, systimestamp
        );
    END add_row;

    FUNCTION reason(p_row IN PLS_INTEGER) RETURN VARCHAR2 IS
        l_reason slv_rej_counterparty.reason_code%TYPE;
    BEGIN
        SELECT max(reason_code) INTO l_reason
        FROM slv_rej_counterparty
        WHERE load_id = g_load_id AND src_row = p_row;
        RETURN l_reason;
    END reason;

    PROCEDURE check_rows IS
    BEGIN
        pkg_silver.reject_counterparties(NULL, g_load_id);
    END check_rows;

    PROCEDURE c01_boundaries IS
    BEGIN
        add_row(1, 'cpty_id', rpad('C', 20, 'X'));
        add_row(2, 'cpty_id', rpad('D', 21, 'X'));
        add_row(3, 'cpty_id', '   ');
        add_row(4, 'cpty_name', rpad('x', 200, 'x'));
        add_row(5, 'cpty_name', rpad('x', 201, 'x'));
        check_rows;
        ut.expect(reason(1)).to_be_null();
        ut.expect(reason(2)).to_equal('C01');
        ut.expect(reason(3)).to_equal('C01');
        ut.expect(reason(4)).to_be_null();
        ut.expect(reason(5)).to_equal('C01');
    END c01_boundaries;

    PROCEDURE c02_boundaries IS
    BEGIN
        add_row(1, 'as_of_date', '2001-02-30');
        add_row(2, 'as_of_date', '2001-1-31');
        add_row(3, 'as_of_date', '2000-12-31');
        add_row(4, 'as_of_date', ' 2001-01-31 ');
        check_rows;
        ut.expect(reason(1)).to_equal('C02');
        ut.expect(reason(2)).to_equal('C02');
        ut.expect(reason(3)).to_equal('C02');
        ut.expect(reason(4)).to_be_null();
    END c02_boundaries;

    PROCEDURE c03_boundaries IS
    BEGIN
        add_row(1, 'segment_code', 'corporate');
        add_row(2, 'segment_code', ' CORPORATE ');
        add_row(3, 'segment_code', '');
        check_rows;
        ut.expect(reason(1)).to_equal('C03');
        ut.expect(reason(2)).to_be_null();
        ut.expect(reason(3)).to_equal('C03');
    END c03_boundaries;

    PROCEDURE c04_boundaries IS
    BEGIN
        add_row(1, 'rating', 'NR');
        add_row(2, 'rating', 'C');
        add_row(3, 'rating', 'aaa');
        check_rows;
        ut.expect(reason(1)).to_be_null();
        ut.expect(reason(2)).to_equal('C04');
        ut.expect(reason(3)).to_equal('C04');
    END c04_boundaries;

    PROCEDURE c05_boundaries IS
    BEGIN
        add_row(1, 'default_flag', 'y');
        add_row(2, 'default_flag', '');
        add_row(3, 'default_flag', 'N');
        check_rows;
        ut.expect(reason(1)).to_equal('C05');
        ut.expect(reason(2)).to_equal('C05');
        ut.expect(reason(3)).to_be_null();
    END c05_boundaries;

    PROCEDURE c06_boundaries IS
    BEGIN
        add_row(1, 'lei', lower(g_lei));
        add_row(2, 'lei', '');
        add_row(3, 'lei', substr(g_lei, 1, 19) || translate(substr(g_lei, 20, 1), '0123456789', '1234567890'));
        add_row(4, 'segment_code', 'SME', 'lei', '');
        add_row(5, 'segment_code', 'RETAIL');
        check_rows;
        ut.expect(reason(1)).to_equal('C06');
        ut.expect(reason(2)).to_equal('C06');
        ut.expect(reason(3)).to_equal('C06');
        ut.expect(reason(4)).to_be_null();
        ut.expect(reason(5)).to_be_null();
    END c06_boundaries;

    PROCEDURE c07_boundaries IS
    BEGIN
        add_row(1, 'country', 'FR');
        add_row(2, 'country', 'fr');
        add_row(3, 'country', 'FRA');
        check_rows;
        ut.expect(reason(1)).to_be_null();
        ut.expect(reason(2)).to_equal('C07');
        ut.expect(reason(3)).to_equal('C07');
    END c07_boundaries;

    PROCEDURE c08_boundaries IS
    BEGIN
        add_row(1);
        add_row(2, 'cpty_id', 'CP00000001');
        add_row(3, 'cpty_id', 'DUPL1');
        add_row(4, 'cpty_id', 'DUPL1 ');
        add_row(5, 'cpty_id', 'DUPL2');
        add_row(6, 'cpty_id', 'DUPL2', 'rating', 'C');
        check_rows;
        ut.expect(reason(1)).to_equal('C08');
        ut.expect(reason(2)).to_equal('C08');
        ut.expect(reason(3)).to_equal('C08');
        ut.expect(reason(4)).to_equal('C08');
        ut.expect(reason(5)).to_equal('C08');
        ut.expect(reason(6)).to_equal('C04');
    END c08_boundaries;

    PROCEDURE first_failing_rule_wins IS
    BEGIN
        add_row(1, 'segment_code', 'corporate', 'country', 'fr');
        add_row(2, 'as_of_date', 'not a date', 'rating', 'C');
        add_row(3, 'cpty_name', '', 'default_flag', 'y');
        check_rows;
        ut.expect(reason(1)).to_equal('C03');
        ut.expect(reason(2)).to_equal('C02');
        ut.expect(reason(3)).to_equal('C01');
    END first_failing_rule_wins;

    PROCEDURE c06_gleif_sample IS
        l_sample_rejects PLS_INTEGER;
        l_variant_c06 PLS_INTEGER;
        l_variants PLS_INTEGER;
    BEGIN
        INSERT INTO brz_counterparty (
            cpty_id, cpty_name, lei, segment_code, country, rating, default_flag, as_of_date,
            load_id, src_file, src_row, ingested_at
        )
        SELECT
            'G' || lpad(rownum, 8, '0') AS cpty_id,
            'Gleif Sample SA' AS cpty_name,
            lei,
            'CORPORATE' AS segment_code,
            'FR' AS country,
            'BBB' AS rating,
            'N' AS default_flag,
            '2001-01-31' AS as_of_date,
            g_load_id AS load_id,
            'ut_silver' AS src_file,
            rownum AS src_row,
            systimestamp AS ingested_at
        FROM ut_lei_gleif;
        INSERT INTO brz_counterparty (
            cpty_id, cpty_name, lei, segment_code, country, rating, default_flag, as_of_date,
            load_id, src_file, src_row, ingested_at
        )
        SELECT
            'V' || lpad(rownum, 8, '0') AS cpty_id,
            'Gleif Variant SA' AS cpty_name,
            substr(g.lei, 1, p.n - 1)
            || translate(
                substr(g.lei, p.n, 1),
                '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                '1234567890BCDEFGHIJKLMNOPQRSTUVWXYZA'
            )
            || substr(g.lei, p.n + 1) AS lei,
            'CORPORATE' AS segment_code,
            'FR' AS country,
            'BBB' AS rating,
            'N' AS default_flag,
            '2001-01-31' AS as_of_date,
            g_load_id AS load_id,
            'ut_silver' AS src_file,
            1000 + rownum AS src_row,
            systimestamp AS ingested_at
        FROM ut_lei_gleif g
        CROSS JOIN (
            SELECT LEVEL AS n FROM dual
            CONNECT BY LEVEL <= 20
        ) p;
        l_variants := SQL%ROWCOUNT;
        check_rows;
        SELECT count(*) INTO l_sample_rejects
        FROM slv_rej_counterparty
        WHERE load_id = g_load_id AND src_row <= 1000;
        SELECT count(*) INTO l_variant_c06
        FROM slv_rej_counterparty
        WHERE load_id = g_load_id AND src_row > 1000 AND reason_code = 'C06';
        ut.expect(l_sample_rejects).to_equal(0);
        ut.expect(l_variants).to_equal(20000);
        ut.expect(l_variant_c06).to_equal(l_variants);
    END c06_gleif_sample;

    PROCEDURE accepted_rows_typed IS
        l_silver slv_counterparty%ROWTYPE;
        l_rows PLS_INTEGER;
        l_accented PLS_INTEGER;
    BEGIN
        add_row(1, 'cpty_name', '  Atlas Foods SA  ', 'segment_code', ' CORPORATE ');
        add_row(2, 'rating', 'C');
        add_row(3, 'cpty_name', rpad('é', 200, 'é'));
        check_rows;
        pkg_silver.insert_counterparties(NULL, g_load_id);
        SELECT count(*) INTO l_rows
        FROM slv_counterparty
        WHERE load_id = g_load_id;
        SELECT * INTO l_silver
        FROM slv_counterparty
        WHERE load_id = g_load_id AND src_row = 1;
        SELECT count(*) INTO l_accented
        FROM slv_counterparty
        WHERE load_id = g_load_id AND src_row = 3 AND length(cpty_name) = 200;
        ut.expect(l_rows).to_equal(2);
        ut.expect(l_silver.cpty_name).to_equal('Atlas Foods SA');
        ut.expect(l_silver.segment_code).to_equal('CORPORATE');
        ut.expect(l_silver.as_of_date).to_equal(c_as_of);
        ut.expect(l_accented).to_equal(1);
    END accepted_rows_typed;

    PROCEDURE rejects_required_before_silver IS
    BEGIN
        add_row(1);
        pkg_silver.insert_counterparties(NULL, g_load_id);
    END rejects_required_before_silver;
END ut_silver;
/
