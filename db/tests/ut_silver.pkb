ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY ut_silver AS
    c_as_of CONSTANT DATE := DATE '2001-01-31';
    g_load_id ops_load_registry.load_id%TYPE;
    g_expo_load_id ops_load_registry.load_id%TYPE;
    g_lei ut_lei_gleif.lei%TYPE;

    PROCEDURE setup IS
    BEGIN
        INSERT INTO ops_load_registry (feed, as_of_date, file_path, sha256, rows_expected, status, started_at)
        VALUES ('counterparty', c_as_of, 'ut_silver', rpad('0', 64, '0'), 0, 'LOADED', systimestamp)
        RETURNING load_id INTO g_load_id;
        INSERT INTO ops_load_registry (feed, as_of_date, file_path, sha256, rows_expected, status, started_at)
        VALUES ('exposure', c_as_of, 'ut_silver', rpad('0', 64, '0'), 0, 'LOADED', systimestamp)
        RETURNING load_id INTO g_expo_load_id;
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

    PROCEDURE add_exposure(
        p_row IN PLS_INTEGER,
        p_column IN VARCHAR2 DEFAULT NULL,
        p_value IN VARCHAR2 DEFAULT NULL,
        p_column_2 IN VARCHAR2 DEFAULT NULL,
        p_value_2 IN VARCHAR2 DEFAULT NULL
    ) IS
        l_exposure_id brz_exposure.exposure_id%TYPE
            := pick('exposure_id', 'EX' || lpad(p_row, 10, '0'), p_column, p_value, p_column_2, p_value_2);
        l_cpty_id brz_exposure.cpty_id%TYPE := pick('cpty_id', 'CP00000001', p_column, p_value, p_column_2, p_value_2);
        l_product brz_exposure.product_code%TYPE
            := pick('product_code', 'LOAN', p_column, p_value, p_column_2, p_value_2);
        l_drawn brz_exposure.drawn_amt%TYPE := pick('drawn_amt', '1000.00', p_column, p_value, p_column_2, p_value_2);
        l_undrawn brz_exposure.undrawn_amt%TYPE
            := pick('undrawn_amt', '0.00', p_column, p_value, p_column_2, p_value_2);
        l_collateral brz_exposure.collateral_amt%TYPE
            := pick('collateral_amt', '', p_column, p_value, p_column_2, p_value_2);
        l_type brz_exposure.collateral_type%TYPE
            := pick('collateral_type', '', p_column, p_value, p_column_2, p_value_2);
        l_currency brz_exposure.currency%TYPE := pick('currency', 'EUR', p_column, p_value, p_column_2, p_value_2);
        l_date brz_exposure.as_of_date%TYPE
            := pick('as_of_date', '2001-01-31', p_column, p_value, p_column_2, p_value_2);
    BEGIN
        INSERT INTO brz_exposure (
            exposure_id, cpty_id, product_code, drawn_amt, undrawn_amt, collateral_amt, collateral_type, currency,
            as_of_date, load_id, src_file, src_row, ingested_at
        )
        VALUES (
            l_exposure_id, l_cpty_id, l_product, l_drawn, l_undrawn, l_collateral, l_type, l_currency,
            l_date, g_expo_load_id, 'ut_silver', p_row, systimestamp
        );
    END add_exposure;

    FUNCTION expo_reason(p_row IN PLS_INTEGER) RETURN VARCHAR2 IS
        l_reason slv_rej_exposure.reason_code%TYPE;
    BEGIN
        SELECT max(reason_code) INTO l_reason
        FROM slv_rej_exposure
        WHERE load_id = g_expo_load_id AND src_row = p_row;
        RETURN l_reason;
    END expo_reason;

    PROCEDURE check_exposures IS
    BEGIN
        pkg_silver.reject_counterparties(NULL, g_load_id);
        pkg_silver.reject_exposures(NULL, g_expo_load_id, g_load_id);
    END check_exposures;

    FUNCTION row_count(p_table IN VARCHAR2, p_load_id IN NUMBER) RETURN NUMBER IS
        l_rows NUMBER;
    BEGIN
        EXECUTE IMMEDIATE 'SELECT count(*) FROM ' || dbms_assert.simple_sql_name(p_table) || ' WHERE load_id = :1'
        INTO l_rows USING p_load_id;
        RETURN l_rows;
    END row_count;

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
        check_exposures;
        pkg_silver.replace_as_of(NULL, g_load_id, g_expo_load_id);
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
        pkg_silver.replace_as_of(NULL, g_load_id, g_expo_load_id);
    END rejects_required_before_silver;

    PROCEDURE r01_boundaries IS
    BEGIN
        add_row(1);
        add_exposure(1, 'exposure_id', rpad('E', 30, 'X'));
        add_exposure(2, 'exposure_id', rpad('F', 31, 'X'));
        add_exposure(3, 'cpty_id', '');
        check_exposures;
        ut.expect(expo_reason(1)).to_be_null();
        ut.expect(expo_reason(2)).to_equal('R01');
        ut.expect(expo_reason(3)).to_equal('R01');
    END r01_boundaries;

    PROCEDURE r02_boundaries IS
    BEGIN
        add_row(1);
        add_exposure(1, 'drawn_amt', rpad('1', 16, '1'));
        add_exposure(2, 'drawn_amt', rpad('1', 17, '1'));
        add_exposure(3, 'drawn_amt', '1e3');
        add_exposure(4, 'drawn_amt', '1,50');
        add_exposure(5, 'drawn_amt', '1.505');
        add_exposure(6, 'collateral_amt', 'abc', 'collateral_type', 'CASH');
        add_exposure(7, 'drawn_amt', '-0.01');
        check_exposures;
        ut.expect(expo_reason(1)).to_be_null();
        ut.expect(expo_reason(2)).to_equal('R02');
        ut.expect(expo_reason(3)).to_equal('R02');
        ut.expect(expo_reason(4)).to_equal('R02');
        ut.expect(expo_reason(5)).to_equal('R02');
        ut.expect(expo_reason(6)).to_equal('R02');
        ut.expect(expo_reason(7)).to_equal('R03');
    END r02_boundaries;

    PROCEDURE r03_boundaries IS
    BEGIN
        add_row(1);
        add_exposure(1, 'drawn_amt', '-0.01');
        add_exposure(2, 'drawn_amt', '0');
        add_exposure(3, 'drawn_amt', '-0');
        check_exposures;
        ut.expect(expo_reason(1)).to_equal('R03');
        ut.expect(expo_reason(2)).to_be_null();
        ut.expect(expo_reason(3)).to_be_null();
    END r03_boundaries;

    PROCEDURE r04_boundaries IS
    BEGIN
        add_row(1);
        add_exposure(1);
        add_exposure(2, 'product_code', 'loan');
        check_exposures;
        ut.expect(expo_reason(1)).to_be_null();
        ut.expect(expo_reason(2)).to_equal('R04');
    END r04_boundaries;

    PROCEDURE r05_boundaries IS
    BEGIN
        add_row(1);
        add_exposure(1, 'as_of_date', '2001-1-31');
        add_exposure(2, 'as_of_date', '2000-12-31');
        add_exposure(3);
        check_exposures;
        ut.expect(expo_reason(1)).to_equal('R05');
        ut.expect(expo_reason(2)).to_equal('R05');
        ut.expect(expo_reason(3)).to_be_null();
    END r05_boundaries;

    PROCEDURE r06_boundaries IS
    BEGIN
        add_row(1);
        add_exposure(1, 'exposure_id', 'DUP1');
        add_exposure(2, 'exposure_id', 'DUP1 ');
        add_exposure(3, 'exposure_id', 'DUP2');
        add_exposure(4, 'exposure_id', 'DUP2', 'drawn_amt', '1e3');
        check_exposures;
        ut.expect(expo_reason(1)).to_equal('R06');
        ut.expect(expo_reason(2)).to_equal('R06');
        ut.expect(expo_reason(3)).to_equal('R06');
        ut.expect(expo_reason(4)).to_equal('R02');
    END r06_boundaries;

    PROCEDURE r07_boundaries IS
    BEGIN
        add_row(1);
        add_row(2, 'rating', 'C');
        add_row(3, 'cpty_id', 'DUPL');
        add_row(4, 'cpty_id', 'DUPL');
        add_exposure(1);
        add_exposure(2, 'cpty_id', 'CP00000002');
        add_exposure(3, 'cpty_id', 'CP00000002', 'drawn_amt', '1e3');
        add_exposure(4, 'cpty_id', 'DUPL');
        add_exposure(5, 'cpty_id', 'CP99999999');
        check_exposures;
        ut.expect(expo_reason(1)).to_be_null();
        ut.expect(expo_reason(2)).to_equal('R07');
        ut.expect(expo_reason(3)).to_equal('R02');
        ut.expect(expo_reason(4)).to_equal('R07');
        ut.expect(expo_reason(5)).to_equal('R07');
    END r07_boundaries;

    PROCEDURE r08_boundaries IS
    BEGIN
        add_row(1);
        add_exposure(1, 'collateral_amt', '0.00');
        add_exposure(2, 'collateral_amt', '');
        add_exposure(3, 'collateral_amt', '0.01');
        check_exposures;
        ut.expect(expo_reason(1)).to_be_null();
        ut.expect(expo_reason(2)).to_be_null();
        ut.expect(expo_reason(3)).to_equal('R08');
    END r08_boundaries;

    PROCEDURE r09_boundaries IS
    BEGIN
        add_row(1);
        add_exposure(1, 'collateral_amt', '100.00', 'collateral_type', 'CASH');
        add_exposure(2, 'collateral_amt', '100.00', 'collateral_type', 'cash');
        add_exposure(3, 'collateral_type', '');
        check_exposures;
        ut.expect(expo_reason(1)).to_be_null();
        ut.expect(expo_reason(2)).to_equal('R09');
        ut.expect(expo_reason(3)).to_be_null();
    END r09_boundaries;

    PROCEDURE r10_boundaries IS
    BEGIN
        add_row(1);
        add_exposure(1, 'undrawn_amt', '0.01');
        add_exposure(2, 'product_code', 'GUARANTEE', 'drawn_amt', '0.01');
        add_exposure(3, 'product_code', 'UNDRAWN_LINE', 'undrawn_amt', '500.00');
        check_exposures;
        ut.expect(expo_reason(1)).to_equal('R10');
        ut.expect(expo_reason(2)).to_equal('R10');
        ut.expect(expo_reason(3)).to_be_null();
    END r10_boundaries;

    PROCEDURE r11_boundaries IS
    BEGIN
        add_row(1);
        add_exposure(1, 'currency', 'eur');
        add_exposure(2, 'currency', 'USD');
        add_exposure(3, 'currency', 'EUR');
        check_exposures;
        ut.expect(expo_reason(1)).to_equal('R11');
        ut.expect(expo_reason(2)).to_equal('R11');
        ut.expect(expo_reason(3)).to_be_null();
    END r11_boundaries;

    PROCEDURE reconciliation_exact IS
        l_collateral slv_exposure.collateral_amt%TYPE;
    BEGIN
        add_row(1);
        add_row(2, 'rating', 'C');
        add_exposure(1);
        add_exposure(2, 'cpty_id', 'CP00000002');
        add_exposure(3, 'currency', 'USD');
        check_exposures;
        pkg_silver.replace_as_of(NULL, g_load_id, g_expo_load_id);
        SELECT collateral_amt INTO l_collateral
        FROM slv_exposure
        WHERE load_id = g_expo_load_id AND src_row = 1;
        ut.expect(row_count('BRZ_COUNTERPARTY', g_load_id)).to_equal(
            row_count('SLV_COUNTERPARTY', g_load_id) + row_count('SLV_REJ_COUNTERPARTY', g_load_id)
        );
        ut.expect(row_count('BRZ_EXPOSURE', g_expo_load_id)).to_equal(
            row_count('SLV_EXPOSURE', g_expo_load_id) + row_count('SLV_REJ_EXPOSURE', g_expo_load_id)
        );
        ut.expect(row_count('SLV_EXPOSURE', g_expo_load_id)).to_equal(1);
        ut.expect(l_collateral).to_equal(0);
    END reconciliation_exact;

    PROCEDURE rejects_replaced_per_load IS
        l_first NUMBER;
        l_registry ops_load_registry.rows_rejected%TYPE;
    BEGIN
        add_row(1);
        add_exposure(1, 'currency', 'USD');
        add_exposure(2);
        check_exposures;
        l_first := row_count('SLV_REJ_EXPOSURE', g_expo_load_id);
        check_exposures;
        SELECT rows_rejected INTO l_registry
        FROM ops_load_registry
        WHERE load_id = g_expo_load_id;
        ut.expect(l_first).to_equal(1);
        ut.expect(row_count('SLV_REJ_EXPOSURE', g_expo_load_id)).to_equal(l_first);
        ut.expect(l_registry).to_equal(l_first);
    END rejects_replaced_per_load;
END ut_silver;
/
