ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY ut_params AS
    PROCEDURE version_complete IS
        l_validities NUMBER;
        l_missing NUMBER;
        l_unexpected NUMBER;
    BEGIN
        SELECT count(*) INTO l_validities
        FROM (
            SELECT param_version FROM (
                SELECT param_version, valid_from, valid_to FROM param_ccf
                UNION
                SELECT param_version, valid_from, valid_to FROM param_haircut
                UNION
                SELECT param_version, valid_from, valid_to FROM param_risk_weight
            )
            GROUP BY param_version
            HAVING count(*) > 1
        );
        WITH versions AS (
            SELECT param_version FROM param_ccf
            UNION
            SELECT param_version FROM param_haircut
            UNION
            SELECT param_version FROM param_risk_weight
        ),

        classes AS (
            SELECT segment_code AS exposure_class FROM ref_segment
            UNION ALL
            SELECT 'DEFAULTED' AS exposure_class FROM dual
        ),

        expected AS (
            SELECT
                v.param_version,
                'CCF' AS kind,
                p.product_code AS key_1,
                '-' AS key_2
            FROM versions v CROSS JOIN ref_product p
            UNION ALL
            SELECT
                v.param_version,
                'HAIRCUT' AS kind,
                t.collateral_type AS key_1,
                '-' AS key_2
            FROM versions v CROSS JOIN ref_collateral_type t
            UNION ALL
            SELECT
                v.param_version,
                'WEIGHT' AS kind,
                c.exposure_class AS key_1,
                b.rating_bucket AS key_2
            FROM versions v
            CROSS JOIN classes c
            CROSS JOIN (SELECT DISTINCT rating_bucket FROM ref_rating) b
        ),

        actual AS (
            SELECT
                param_version,
                'CCF' AS kind,
                product_code AS key_1,
                '-' AS key_2
            FROM param_ccf
            UNION ALL
            SELECT
                param_version,
                'HAIRCUT' AS kind,
                collateral_type AS key_1,
                '-' AS key_2
            FROM param_haircut
            UNION ALL
            SELECT
                param_version,
                'WEIGHT' AS kind,
                exposure_class AS key_1,
                rating_bucket AS key_2
            FROM param_risk_weight
        )

        SELECT
            (SELECT count(*) FROM (SELECT * FROM expected MINUS SELECT * FROM actual)) AS missing,
            (SELECT count(*) FROM (SELECT * FROM actual MINUS SELECT * FROM expected)) AS unexpected
        INTO l_missing, l_unexpected
        FROM dual;
        ut.expect(l_validities).to_equal(0);
        ut.expect(l_missing).to_equal(0);
        ut.expect(l_unexpected).to_equal(0);
    END version_complete;

    PROCEDURE no_overlap_full_coverage IS
        l_breaks NUMBER;
        l_tables NUMBER;
    BEGIN
        WITH versions AS (
            SELECT DISTINCT
                'CCF' AS kind,
                param_version,
                valid_from,
                valid_to
            FROM param_ccf
            UNION ALL
            SELECT DISTINCT
                'HAIRCUT' AS kind,
                param_version,
                valid_from,
                valid_to
            FROM param_haircut
            UNION ALL
            SELECT DISTINCT
                'WEIGHT' AS kind,
                param_version,
                valid_from,
                valid_to
            FROM param_risk_weight
        ),

        chained AS (
            SELECT
                kind,
                valid_from,
                valid_to,
                lag(valid_to) OVER (PARTITION BY kind ORDER BY valid_from) AS previous_to,
                row_number() OVER (PARTITION BY kind ORDER BY valid_from) AS position,
                count(*) OVER (PARTITION BY kind) AS total
            FROM versions
        )

        SELECT
            count(CASE
                WHEN position = 1 AND valid_from != DATE '2000-01-01' THEN 1
                WHEN position > 1 AND valid_from != previous_to THEN 1
                WHEN position = total AND valid_to != pkg_gold.c_open_end THEN 1
            END) AS breaks,
            count(DISTINCT kind) AS tables
        INTO l_breaks, l_tables
        FROM chained;
        ut.expect(l_breaks).to_equal(0);
        ut.expect(l_tables).to_equal(3);
    END no_overlap_full_coverage;
END ut_params;
/
