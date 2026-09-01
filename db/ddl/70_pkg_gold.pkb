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

    PROCEDURE load_facts(p_run_id IN NUMBER, p_as_of_date IN DATE) IS
    BEGIN
        DELETE FROM gld_fact_exposure
        WHERE as_of_date = p_as_of_date;
        INSERT INTO gld_fact_exposure (
            as_of_date, date_sk, cpty_sk, product_sk, segment_code, exposure_id,
            drawn_amt, undrawn_amt, collateral_amt, collateral_type, run_id
        )
        WITH params AS (
            SELECT
                p_as_of_date AS as_of_date,
                p_run_id AS run_id
            FROM dual
        )

        SELECT
            s.as_of_date,
            d.date_sk,
            c.cpty_sk,
            p.product_sk,
            c.segment_code,
            s.exposure_id,
            s.drawn_amt,
            s.undrawn_amt,
            s.collateral_amt,
            s.collateral_type,
            x.run_id
        FROM params x
        INNER JOIN slv_exposure s ON x.as_of_date = s.as_of_date
        INNER JOIN gld_dim_date d ON s.as_of_date = d.calendar_date
        INNER JOIN gld_dim_counterparty c
            ON s.cpty_id = c.cpty_id AND s.as_of_date >= c.valid_from AND s.as_of_date < c.valid_to
        INNER JOIN gld_dim_product p ON s.product_code = p.product_code;
    END load_facts;

    PROCEDURE build_as_of(p_run_id IN NUMBER, p_as_of_date IN DATE) IS -- F4
    BEGIN
        load_counterparties(p_run_id, p_as_of_date);
        load_facts(p_run_id, p_as_of_date);
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'build_as_of');
                RAISE;
    END build_as_of;

    PROCEDURE finish_as_of(p_run_id IN NUMBER, p_as_of_date IN DATE, p_rows OUT NUMBER) IS
        l_silver NUMBER;
        l_facts NUMBER;
        l_rwa NUMBER;
    BEGIN
        SELECT count(*) INTO l_silver
        FROM slv_exposure
        WHERE as_of_date = p_as_of_date;
        SELECT count(*) INTO l_facts
        FROM gld_fact_exposure
        WHERE as_of_date = p_as_of_date;
        SELECT count(*) INTO l_rwa
        FROM gld_fact_rwa
        WHERE as_of_date = p_as_of_date;
        IF l_facts != l_silver OR l_rwa != l_silver THEN
            raise_application_error(
                c_counts,
                to_char(p_as_of_date, 'YYYY-MM-DD') || ': ' || l_silver || ' silver, ' || l_facts || ' facts, '
                || l_rwa || ' rwa'
            );
        END IF;
        p_rows := l_facts;
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'finish_as_of');
                RAISE;
    END finish_as_of;

    PROCEDURE rewind(p_run_id IN NUMBER, p_from IN DATE) IS -- F4
    BEGIN
        DELETE FROM gld_fact_rwa
        WHERE as_of_date >= p_from;
        DELETE FROM gld_fact_exposure
        WHERE as_of_date >= p_from;
        DELETE FROM gld_dim_counterparty
        WHERE valid_from >= p_from;
        UPDATE gld_dim_counterparty
        SET
            valid_to = c_open_end,
            is_current = 'Y'
        WHERE valid_from < p_from AND valid_to >= p_from AND valid_to < c_open_end;
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'rewind');
                RAISE;
    END rewind;
END pkg_gold;
/
