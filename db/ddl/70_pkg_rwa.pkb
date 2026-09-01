ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY pkg_rwa AS
    c_he CONSTANT NUMBER := 0;
    c_hfx CONSTANT NUMBER := 0;

    PROCEDURE compute(p_run_id IN NUMBER, p_as_of_date IN DATE) IS -- F5
    BEGIN
        DELETE FROM gld_fact_rwa
        WHERE as_of_date = p_as_of_date;
        INSERT INTO gld_fact_rwa (
            as_of_date, date_sk, cpty_sk, product_sk, segment_code, exposure_id, exposure_class, rating_bucket,
            ccf, ead, hc, e_star, risk_weight, rwa, param_version, run_id
        )
        WITH params AS (
            SELECT
                p_as_of_date AS as_of_date,
                p_run_id AS run_id,
                c_he AS he,
                c_hfx AS hfx
            FROM dual
        ),

        version AS (
            SELECT DISTINCT
                w.param_version,
                x.as_of_date,
                x.run_id,
                x.he,
                x.hfx
            FROM params x
            INNER JOIN param_risk_weight w ON x.as_of_date >= w.valid_from AND x.as_of_date < w.valid_to
        ),

        chain AS (
            SELECT
                f.as_of_date,
                f.date_sk,
                f.cpty_sk,
                f.product_sk,
                f.segment_code,
                f.exposure_id,
                CASE c.default_flag WHEN 'Y' THEN 'DEFAULTED' ELSE f.segment_code END AS exposure_class, -- F5.1
                r.rating_bucket, -- F5.2
                k.ccf,
                f.drawn_amt + k.ccf * f.undrawn_amt AS ead, -- F5.3
                nvl2(f.collateral_type, h.haircut, 0) AS hc,
                f.collateral_amt,
                v.he,
                v.hfx,
                v.param_version,
                v.run_id
            FROM version v
            INNER JOIN gld_fact_exposure f ON v.as_of_date = f.as_of_date
            INNER JOIN gld_dim_counterparty c ON f.cpty_sk = c.cpty_sk
            INNER JOIN ref_rating r ON c.rating = r.rating_code
            INNER JOIN gld_dim_product p ON f.product_sk = p.product_sk
            INNER JOIN param_ccf k ON v.param_version = k.param_version AND p.product_code = k.product_code
            LEFT JOIN param_haircut h ON v.param_version = h.param_version AND f.collateral_type = h.collateral_type
        ),

        mitigated AS (
            SELECT
                as_of_date,
                date_sk,
                cpty_sk,
                product_sk,
                segment_code,
                exposure_id,
                exposure_class,
                rating_bucket,
                ccf,
                ead,
                hc,
                greatest(0, ead * (1 + he) - collateral_amt * (1 - hc - hfx)) AS e_star, -- F5.4
                param_version,
                run_id
            FROM chain
        )

        SELECT
            m.as_of_date,
            m.date_sk,
            m.cpty_sk,
            m.product_sk,
            m.segment_code,
            m.exposure_id,
            m.exposure_class,
            m.rating_bucket,
            m.ccf,
            m.ead,
            m.hc,
            m.e_star,
            w.risk_weight,
            round(m.e_star * w.risk_weight, 2) AS rwa, -- F5.5
            m.param_version,
            m.run_id
        FROM mitigated m
        INNER JOIN param_risk_weight w
            ON
                m.param_version = w.param_version
                AND m.exposure_class = w.exposure_class
                AND m.rating_bucket = w.rating_bucket;
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'compute');
                RAISE;
    END compute;
END pkg_rwa;
/
