ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY pkg_gold AS
    PROCEDURE load_counterparties(p_run_id IN NUMBER, p_as_of_date IN DATE) IS -- F4
    BEGIN
        UPDATE gld_dim_counterparty d
        SET
            d.valid_to = p_as_of_date,
            d.is_current = 'N'
        WHERE
            d.is_current = 'Y'
            AND EXISTS (
                SELECT 1 FROM slv_counterparty s
                WHERE
                    s.as_of_date = p_as_of_date
                    AND s.cpty_id = d.cpty_id
                    AND (s.segment_code != d.segment_code OR s.rating != d.rating OR s.default_flag != d.default_flag)
            );
        INSERT INTO gld_dim_counterparty (
            cpty_id, segment_code, rating, default_flag, cpty_name, lei, country, valid_from, valid_to, is_current
        )
        SELECT
            s.cpty_id,
            s.segment_code,
            s.rating,
            s.default_flag,
            s.cpty_name,
            s.lei,
            s.country,
            p_as_of_date AS valid_from,
            c_open_end AS valid_to,
            'Y' AS is_current
        FROM slv_counterparty s
        WHERE
            s.as_of_date = p_as_of_date
            AND NOT EXISTS (
                SELECT 1 FROM gld_dim_counterparty d
                WHERE d.cpty_id = s.cpty_id AND d.is_current = 'Y'
            );
        MERGE INTO gld_dim_counterparty d
        USING (
            SELECT
                cpty_id,
                cpty_name,
                lei,
                country
            FROM slv_counterparty
            WHERE as_of_date = p_as_of_date
        ) s
            ON (d.cpty_id = s.cpty_id)
        WHEN MATCHED THEN UPDATE
            SET
                d.cpty_name = s.cpty_name,
                d.lei = s.lei,
                d.country = s.country
        WHERE
            decode(d.cpty_name, s.cpty_name, 0, 1) + decode(d.lei, s.lei, 0, 1)
            + decode(d.country, s.country, 0, 1) > 0;
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'load_counterparties');
                RAISE;
    END load_counterparties;
END pkg_gold;
/
