ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY ut_views AS
    c_jan CONSTANT DATE := DATE '2001-01-31';

    PROCEDURE rwa_by_class_matches_mart IS
        l_actual SYS_REFCURSOR;
        l_expected SYS_REFCURSOR;
    BEGIN
        ut_data.add_counterparty(c_jan, 'UTV1', p_segment => 'CORPORATE', p_default => 'Y');
        ut_data.add_counterparty(c_jan, 'UTV2', p_default => 'Y');
        ut_data.add_counterparty(c_jan, 'UTV3');
        ut_data.add_exposure(c_jan, 'UTVE1', 'UTV1', p_drawn => 1000);
        ut_data.add_exposure(c_jan, 'UTVE2', 'UTV2', p_drawn => 2000);
        ut_data.add_exposure(c_jan, 'UTVE3', 'UTV3', p_drawn => 1000);
        ut_data.build(c_jan);
        OPEN l_actual FOR
            SELECT exposure_class, risk_weight, n_exposures, exposure_value, rwea
            FROM v_rwa_by_class
            WHERE as_of_date = c_jan
            ORDER BY exposure_class;
        OPEN l_expected FOR
            SELECT
                g.exposure_class,
                g.risk_weight,
                g.n_exposures,
                g.exposure_value,
                g.rwea
            FROM (
                VALUES ('DEFAULTED', 1.5, 2, 3000, 4500), ('SME', 0.85, 1, 1000, 850)
            ) g (exposure_class, risk_weight, n_exposures, exposure_value, rwea)
            ORDER BY g.exposure_class;
        ut.expect(l_actual).to_equal(l_expected);
    END rwa_by_class_matches_mart;

    PROCEDURE rwa_trend_density IS
        l_rows NUMBER;
        l_oldest DATE;
        l_empty NUMBER;
        l_density NUMBER;
    BEGIN
        INSERT INTO gld_mart_rwa (as_of_date, segment_code, exposure_class, risk_weight, n_exposures, ead, e_star, rwa)
        SELECT
            last_day(add_months(c_jan, LEVEL - 1)) AS as_of_date,
            'UT_TREND' AS segment_code,
            'SME' AS exposure_class,
            0.85 AS risk_weight,
            1 AS n_exposures,
            CASE LEVEL WHEN 13 THEN 0 ELSE 1000 END AS ead,
            CASE LEVEL WHEN 13 THEN 0 ELSE 1000 END AS e_star,
            CASE LEVEL WHEN 13 THEN 0 ELSE 500 END AS rwa
        FROM dual
        CONNECT BY LEVEL <= 13;
        SELECT
            count(*),
            min(as_of_date),
            count(CASE WHEN rwa_density IS NULL THEN 1 END),
            max(rwa_density)
        INTO l_rows, l_oldest, l_empty, l_density
        FROM v_rwa_trend
        WHERE segment_code = 'UT_TREND';
        ut.expect(l_rows).to_equal(12);
        ut.expect(l_oldest).to_equal(DATE '2001-02-28');
        ut.expect(l_empty).to_equal(1);
        ut.expect(l_density).to_equal(0.5);
    END rwa_trend_density;

    PROCEDURE top_exposures_ties IS
        l_rows NUMBER;
        l_first VARCHAR2(30);
        l_last VARCHAR2(30);
    BEGIN
        ut_data.add_counterparty(c_jan, 'UTV1');
        INSERT INTO slv_exposure (
            as_of_date, exposure_id, cpty_id, product_code, drawn_amt, undrawn_amt, collateral_amt,
            collateral_type, currency, load_id, src_row
        )
        SELECT
            c_jan AS as_of_date,
            'UTVE' || to_char(LEVEL, 'FM00') AS exposure_id,
            'UTV1' AS cpty_id,
            'LOAN' AS product_code,
            CASE LEVEL WHEN 22 THEN 2000 ELSE 1000 END AS drawn_amt,
            0 AS undrawn_amt,
            0 AS collateral_amt,
            NULL AS collateral_type,
            'EUR' AS currency,
            0 AS load_id,
            LEVEL AS src_row
        FROM dual
        CONNECT BY LEVEL <= 22;
        ut_data.build(c_jan);
        SELECT
            count(*),
            max(exposure_id) KEEP (DENSE_RANK FIRST ORDER BY rwa DESC, exposure_id ASC),
            max(exposure_id) KEEP (DENSE_RANK LAST ORDER BY rwa DESC, exposure_id ASC)
        INTO l_rows, l_first, l_last
        FROM v_top_exposures
        WHERE as_of_date = c_jan;
        ut.expect(l_rows).to_equal(20);
        ut.expect(l_first).to_equal('UTVE22');
        ut.expect(l_last).to_equal('UTVE19');
    END top_exposures_ties;
END ut_views;
/
