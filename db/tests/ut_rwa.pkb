ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY ut_rwa AS
    c_jan CONSTANT DATE := DATE '2001-01-31';
    c_feb CONSTANT DATE := DATE '2001-02-28';
    c_v2_from CONSTANT DATE := DATE '2001-02-01';
    c_golden CONSTANT DATE := DATE '2000-01-31';

    PROCEDURE add_version_2 IS
    BEGIN
        INSERT INTO param_ccf (param_version, product_code, ccf, valid_from, valid_to)
        SELECT
            2 AS param_version,
            product_code,
            CASE product_code WHEN 'UNDRAWN_LINE' THEN 0.5 ELSE ccf END AS ccf,
            c_v2_from AS valid_from,
            valid_to
        FROM param_ccf
        WHERE param_version = 1;
        INSERT INTO param_haircut (param_version, collateral_type, haircut, valid_from, valid_to)
        SELECT
            2 AS param_version,
            collateral_type,
            haircut,
            c_v2_from AS valid_from,
            valid_to
        FROM param_haircut
        WHERE param_version = 1;
        INSERT INTO param_risk_weight (param_version, exposure_class, rating_bucket, risk_weight, valid_from, valid_to)
        SELECT
            2 AS param_version,
            exposure_class,
            rating_bucket,
            risk_weight,
            c_v2_from AS valid_from,
            valid_to
        FROM param_risk_weight
        WHERE param_version = 1;
        UPDATE param_ccf SET valid_to = c_v2_from WHERE param_version = 1;
        UPDATE param_haircut SET valid_to = c_v2_from WHERE param_version = 1;
        UPDATE param_risk_weight SET valid_to = c_v2_from WHERE param_version = 1;
    END add_version_2;

    PROCEDURE param_version_selection IS
        l_jan gld_fact_rwa%ROWTYPE;
        l_feb gld_fact_rwa%ROWTYPE;
    BEGIN
        add_version_2;
        ut_data.add_counterparty(c_jan, 'UTR1', p_segment => 'CORPORATE');
        ut_data.add_exposure(c_jan, 'UTRE1', 'UTR1', p_product => 'UNDRAWN_LINE', p_drawn => 0, p_undrawn => 1000);
        ut_data.build(c_jan);
        ut_data.add_counterparty(c_feb, 'UTR1', p_segment => 'CORPORATE');
        ut_data.add_exposure(c_feb, 'UTRE1', 'UTR1', p_product => 'UNDRAWN_LINE', p_drawn => 0, p_undrawn => 1000);
        ut_data.build(c_feb);
        SELECT * INTO l_jan
        FROM gld_fact_rwa
        WHERE as_of_date = c_jan AND exposure_id = 'UTRE1';
        SELECT * INTO l_feb
        FROM gld_fact_rwa
        WHERE as_of_date = c_feb AND exposure_id = 'UTRE1';
        ut.expect(l_jan.param_version).to_equal(1);
        ut.expect(l_jan.ccf).to_equal(0.4);
        ut.expect(l_jan.ead).to_equal(400);
        ut.expect(l_jan.rwa).to_equal(300);
        ut.expect(l_feb.param_version).to_equal(2);
        ut.expect(l_feb.ccf).to_equal(0.5);
        ut.expect(l_feb.ead).to_equal(500);
        ut.expect(l_feb.rwa).to_equal(375);
    END param_version_selection;

    FUNCTION fact(p_as_of IN DATE, p_exposure_id IN VARCHAR2) RETURN gld_fact_rwa%ROWTYPE IS
        l_fact gld_fact_rwa%ROWTYPE;
    BEGIN
        SELECT * INTO l_fact
        FROM gld_fact_rwa
        WHERE as_of_date = p_as_of AND exposure_id = p_exposure_id;
        RETURN l_fact;
    END fact;

    PROCEDURE golden IS
    BEGIN
        ut_data.load_golden;
        ut_data.build(c_golden);
    END golden;

    PROCEDURE golden_set_exact IS
        l_actual SYS_REFCURSOR;
        l_expected SYS_REFCURSOR;
    BEGIN
        golden;
        OPEN l_actual FOR
            SELECT exposure_id, exposure_class, ead, e_star, risk_weight, rwa
            FROM gld_fact_rwa
            WHERE as_of_date = c_golden
            ORDER BY exposure_id;
        OPEN l_expected FOR
            SELECT
                golden_id AS exposure_id,
                exposure_class,
                ead,
                e_star,
                risk_weight,
                rwa
            FROM ut_golden_rwa
            ORDER BY exposure_id;
        ut.expect(l_actual).to_equal(l_expected);
    END golden_set_exact;

    PROCEDURE golden_total IS
        l_total NUMBER;
        l_rows NUMBER;
    BEGIN
        golden;
        SELECT sum(rwa), count(*) INTO l_total, l_rows
        FROM gld_fact_rwa
        WHERE as_of_date = c_golden;
        ut.expect(l_rows).to_equal(10);
        ut.expect(l_total).to_equal(2211000);
    END golden_total;

    PROCEDURE defaulted_class IS
        l_defaulted gld_fact_rwa%ROWTYPE;
        l_performing gld_fact_rwa%ROWTYPE;
    BEGIN
        ut_data.add_counterparty(c_jan, 'UTR1', p_rating => 'BB', p_segment => 'CORPORATE', p_default => 'Y');
        ut_data.add_counterparty(c_jan, 'UTR2', p_rating => 'BB', p_segment => 'CORPORATE');
        ut_data.add_exposure(c_jan, 'UTRE1', 'UTR1');
        ut_data.add_exposure(c_jan, 'UTRE2', 'UTR2');
        ut_data.build(c_jan);
        l_defaulted := fact(c_jan, 'UTRE1');
        l_performing := fact(c_jan, 'UTRE2');
        ut.expect(l_defaulted.exposure_class).to_equal('DEFAULTED');
        ut.expect(l_defaulted.segment_code).to_equal('CORPORATE');
        ut.expect(l_defaulted.risk_weight).to_equal(1.5);
        ut.expect(l_performing.exposure_class).to_equal('CORPORATE');
        ut.expect(l_performing.risk_weight).to_equal(1);
    END defaulted_class;

    PROCEDURE ccc_bucket IS
        l_fact gld_fact_rwa%ROWTYPE;
    BEGIN
        ut_data.add_counterparty(c_jan, 'UTR1', p_rating => 'CCC', p_segment => 'CORPORATE');
        ut_data.add_exposure(c_jan, 'UTRE1', 'UTR1');
        ut_data.build(c_jan);
        l_fact := fact(c_jan, 'UTRE1');
        ut.expect(l_fact.rating_bucket).to_equal('CCC_C');
        ut.expect(l_fact.risk_weight).to_equal(1.5);
        ut.expect(l_fact.rwa).to_equal(1500);
    END ccc_bucket;

    PROCEDURE rounding_half_cent IS
        l_half gld_fact_rwa%ROWTYPE;
        l_small gld_fact_rwa%ROWTYPE;
    BEGIN
        ut_data.add_counterparty(c_jan, 'UTR1', p_rating => 'NR', p_segment => 'RETAIL');
        ut_data.add_exposure(c_jan, 'UTRE1', 'UTR1', p_drawn => 0.02);
        ut_data.add_exposure(c_jan, 'UTRE2', 'UTR1', p_product => 'UNDRAWN_LINE', p_drawn => 0, p_undrawn => 0.01);
        ut_data.build(c_jan);
        l_half := fact(c_jan, 'UTRE1');
        l_small := fact(c_jan, 'UTRE2');
        ut.expect(l_half.rwa).to_equal(0.02);
        ut.expect(l_small.ead).to_equal(0.004);
        ut.expect(l_small.e_star).to_equal(0.004);
        ut.expect(l_small.rwa).to_equal(0);
    END rounding_half_cent;

    PROCEDURE risk_weight_matrix IS
        l_actual SYS_REFCURSOR;
        l_expected SYS_REFCURSOR;
    BEGIN
        INSERT INTO slv_counterparty (
            as_of_date, cpty_id, cpty_name, lei, segment_code, country, rating, default_flag, load_id, src_row
        )
        WITH classes AS (
            SELECT
                segment_code,
                segment_code AS exposure_class,
                'N' AS default_flag
            FROM ref_segment
            UNION ALL
            SELECT
                'CORPORATE' AS segment_code,
                'DEFAULTED' AS exposure_class,
                'Y' AS default_flag
            FROM dual
        ),

        ratings AS (
            SELECT
                rating_bucket,
                min(rating_code) AS rating_code
            FROM ref_rating
            GROUP BY rating_bucket
        )

        SELECT
            c_jan AS as_of_date,
            c.exposure_class || '/' || r.rating_bucket AS cpty_id,
            'Matrix SA' AS cpty_name,
            NULL AS lei,
            c.segment_code,
            'FR' AS country,
            r.rating_code AS rating,
            c.default_flag,
            0 AS load_id,
            1 AS src_row
        FROM classes c CROSS JOIN ratings r;
        INSERT INTO slv_exposure (
            as_of_date, exposure_id, cpty_id, product_code, drawn_amt, undrawn_amt, collateral_amt,
            collateral_type, currency, load_id, src_row
        )
        SELECT
            as_of_date,
            cpty_id AS exposure_id,
            cpty_id,
            'LOAN' AS product_code,
            1000 AS drawn_amt,
            0 AS undrawn_amt,
            0 AS collateral_amt,
            NULL AS collateral_type,
            'EUR' AS currency,
            0 AS load_id,
            1 AS src_row
        FROM slv_counterparty
        WHERE as_of_date = c_jan;
        ut_data.build(c_jan);
        OPEN l_actual FOR
            SELECT exposure_class, rating_bucket, risk_weight, rwa
            FROM gld_fact_rwa
            WHERE as_of_date = c_jan
            ORDER BY exposure_class, rating_bucket;
        OPEN l_expected FOR
            WITH cells AS (
                SELECT
                    m.exposure_class,
                    b.rating_bucket,
                    CASE b.rating_bucket
                        WHEN 'AAA_AA' THEN m.aaa_aa
                        WHEN 'A' THEN m.a
                        WHEN 'BBB' THEN m.bbb
                        WHEN 'BB' THEN m.bb
                        WHEN 'B' THEN m.b
                        WHEN 'CCC_C' THEN m.ccc_c
                        WHEN 'NR' THEN m.nr
                    END AS risk_weight
                FROM (
                    VALUES
                    ('SOVEREIGN', 0, 0.20, 0.50, 1.00, 1.00, 1.50, 1.00),
                    ('BANK', 0.20, 0.30, 0.50, 1.00, 1.00, 1.50, 1.00),
                    ('CORPORATE', 0.20, 0.50, 0.75, 1.00, 1.50, 1.50, 1.00),
                    ('SME', 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85),
                    ('RETAIL', 0.75, 0.75, 0.75, 0.75, 0.75, 0.75, 0.75),
                    ('DEFAULTED', 1.50, 1.50, 1.50, 1.50, 1.50, 1.50, 1.50)
                ) m (exposure_class, aaa_aa, a, bbb, bb, b, ccc_c, nr)
                CROSS JOIN (VALUES ('AAA_AA'), ('A'), ('BBB'), ('BB'), ('B'), ('CCC_C'), ('NR')) b (rating_bucket)
            )

            SELECT
                exposure_class,
                rating_bucket,
                risk_weight,
                1000 * risk_weight AS rwa
            FROM cells
            ORDER BY exposure_class, rating_bucket;
        ut.expect(l_actual).to_equal(l_expected);
    END risk_weight_matrix;
END ut_rwa;
/
