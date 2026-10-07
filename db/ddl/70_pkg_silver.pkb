ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY pkg_silver AS
    c_amount CONSTANT VARCHAR2(40) := '^-?[0-9]{1,16}(\.[0-9]{1,2})?$';
    c_amount_format CONSTANT VARCHAR2(30) := '9999999999999999D99';
    c_numeric CONSTANT VARCHAR2(40) := 'NLS_NUMERIC_CHARACTERS=''.,''';

    FUNCTION load_as_of(p_load_id IN NUMBER, p_feed IN VARCHAR2) RETURN DATE IS
        l_as_of DATE;
    BEGIN
        SELECT as_of_date INTO l_as_of
        FROM ops_load_registry
        WHERE load_id = p_load_id AND feed = p_feed;
        RETURN l_as_of;
    END load_as_of;

    PROCEDURE reject_counterparties(p_run_id IN NUMBER, p_load_id IN NUMBER) IS -- F3
        l_as_of DATE := load_as_of(p_load_id, 'counterparty');
        l_as_of_text VARCHAR2(10) := to_char(l_as_of, 'YYYY-MM-DD');
        l_rejected PLS_INTEGER;
    BEGIN
        DELETE FROM slv_rej_counterparty
        WHERE load_id = p_load_id;
        INSERT INTO slv_rej_counterparty (
            load_id, src_row, as_of_date, reason_code,
            cpty_id, cpty_name, lei, segment_code, country, rating, default_flag, raw_as_of_date
        )
        WITH src AS (
            SELECT
                load_id,
                src_row,
                cpty_id,
                cpty_name,
                lei,
                segment_code,
                country,
                rating,
                default_flag,
                as_of_date,
                trim(cpty_id) AS t_cpty_id,
                trim(cpty_name) AS t_cpty_name,
                trim(lei) AS t_lei,
                trim(segment_code) AS t_segment_code,
                trim(country) AS t_country,
                trim(rating) AS t_rating,
                trim(default_flag) AS t_default_flag,
                trim(as_of_date) AS t_as_of_date,
                l_as_of_text AS partition_date
            FROM brz_counterparty
            WHERE load_id = p_load_id
        ),

        digits AS (
            SELECT LEVEL AS n FROM dual
            CONNECT BY LEVEL <= 20
        ),

        positions AS (
            SELECT
                s.src_row,
                p.n,
                instr('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ', substr(s.t_lei, p.n, 1)) - 1 AS char_value
            FROM src s
            CROSS JOIN digits p
            WHERE regexp_like(s.t_lei, '^[A-Z0-9]{18}[0-9]{2}$')
        ),

        weighted AS (
            SELECT
                src_row,
                char_value,
                coalesce(sum(CASE WHEN char_value >= 10 THEN 2 ELSE 1 END) OVER (
                    PARTITION BY src_row ORDER BY n DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ), 0) AS digits_after
            FROM positions
        ),

        lei_checksum AS (
            SELECT
                src_row,
                mod(sum(mod(char_value * mod(power(10, digits_after), 97), 97)), 97) AS remainder
            FROM weighted
            GROUP BY src_row
        ),

        joined AS (
            SELECT
                s.*,
                c.remainder
            FROM src s
            LEFT JOIN lei_checksum c ON s.src_row = c.src_row
        ),

        checked AS (
            SELECT
                s.load_id,
                s.src_row,
                s.cpty_id,
                s.cpty_name,
                s.lei,
                s.segment_code,
                s.country,
                s.rating,
                s.default_flag,
                s.as_of_date,
                CASE
                    WHEN
                        s.t_cpty_id IS NULL OR length(s.t_cpty_id) > 20
                        OR s.t_cpty_name IS NULL OR length(s.t_cpty_name) > 200
                        THEN 'C01'
                    WHEN s.t_as_of_date IS NULL OR s.t_as_of_date != s.partition_date THEN 'C02'
                    WHEN NOT EXISTS (
                        SELECT 1 FROM ref_segment r
                        WHERE r.segment_code = s.t_segment_code
                    ) THEN 'C03'
                    WHEN NOT EXISTS (
                        SELECT 1 FROM ref_rating r
                        WHERE r.rating_code = s.t_rating
                    ) THEN 'C04'
                    WHEN s.t_default_flag IS NULL OR s.t_default_flag NOT IN ('Y', 'N') THEN 'C05'
                    WHEN
                        (
                            s.t_lei IS NULL AND EXISTS (
                                SELECT 1 FROM ref_segment r
                                WHERE r.segment_code = s.t_segment_code AND r.lei_required = 'Y'
                            )
                        )
                        OR (s.t_lei IS NOT NULL AND coalesce(s.remainder, -1) != 1)
                        THEN 'C06'
                    WHEN NOT EXISTS (
                        SELECT 1 FROM ref_country r
                        WHERE r.country_code = s.t_country
                    ) THEN 'C07'
                    WHEN count(*) OVER (PARTITION BY s.t_cpty_id) > 1 THEN 'C08'
                END AS reason_code
            FROM joined s
        )

        SELECT
            load_id,
            src_row,
            l_as_of,
            reason_code,
            cpty_id,
            cpty_name,
            lei,
            segment_code,
            country,
            rating,
            default_flag,
            as_of_date
        FROM checked
        WHERE reason_code IS NOT NULL;
        l_rejected := SQL%ROWCOUNT;
        UPDATE ops_load_registry
        SET rows_rejected = l_rejected
        WHERE load_id = p_load_id;
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'reject_counterparties');
                RAISE;
    END reject_counterparties;

    FUNCTION rejected_rows(p_load_id IN NUMBER) RETURN NUMBER IS
        l_rejected ops_load_registry.rows_rejected%TYPE;
    BEGIN
        SELECT rows_rejected INTO l_rejected
        FROM ops_load_registry
        WHERE load_id = p_load_id;
        IF l_rejected IS NULL THEN
            raise_application_error(c_rejects_missing, 'rejects of load ' || p_load_id || ' not computed');
        END IF;
        RETURN l_rejected;
    END rejected_rows;

    PROCEDURE reconcile(p_load_id IN NUMBER, p_bronze IN NUMBER, p_silver IN NUMBER) IS
        l_rejected NUMBER := rejected_rows(p_load_id);
    BEGIN
        IF p_bronze != p_silver + l_rejected THEN
            raise_application_error(
                c_reconciliation,
                'load ' || p_load_id || ': ' || p_bronze || ' bronze rows, '
                || p_silver || ' silver and ' || l_rejected || ' rejected'
            );
        END IF;
    END reconcile;

    PROCEDURE insert_counterparties(p_load_id IN NUMBER, p_as_of IN DATE) IS
        l_inserted PLS_INTEGER;
        l_bronze PLS_INTEGER;
    BEGIN
        INSERT INTO slv_counterparty (
            as_of_date, cpty_id, cpty_name, lei, segment_code, country, rating, default_flag, load_id, src_row
        )
        SELECT
            p_as_of,
            trim(cpty_id) AS cpty_id,
            trim(cpty_name) AS cpty_name,
            trim(lei) AS lei,
            trim(segment_code) AS segment_code,
            trim(country) AS country,
            trim(rating) AS rating,
            trim(default_flag) AS default_flag,
            load_id,
            src_row
        FROM brz_counterparty
        WHERE
            load_id = p_load_id
            AND NOT EXISTS (
                SELECT 1 FROM slv_rej_counterparty r
                WHERE r.load_id = brz_counterparty.load_id AND r.src_row = brz_counterparty.src_row
            );
        l_inserted := SQL%ROWCOUNT;
        SELECT count(*) INTO l_bronze
        FROM brz_counterparty
        WHERE load_id = p_load_id;
        reconcile(p_load_id, l_bronze, l_inserted);
    END insert_counterparties;

    PROCEDURE insert_exposures(p_load_id IN NUMBER, p_as_of IN DATE) IS
        l_inserted PLS_INTEGER;
        l_bronze PLS_INTEGER;
    BEGIN
        INSERT INTO slv_exposure (
            as_of_date, exposure_id, cpty_id, product_code, drawn_amt, undrawn_amt, collateral_amt,
            collateral_type, currency, load_id, src_row
        )
        SELECT
            p_as_of,
            trim(exposure_id) AS exposure_id,
            trim(cpty_id) AS cpty_id,
            trim(product_code) AS product_code,
            to_number(trim(drawn_amt), c_amount_format, c_numeric) AS drawn_amt,
            to_number(trim(undrawn_amt), c_amount_format, c_numeric) AS undrawn_amt,
            coalesce(to_number(trim(collateral_amt), c_amount_format, c_numeric), 0) AS collateral_amt,
            trim(collateral_type) AS collateral_type,
            trim(currency) AS currency,
            load_id,
            src_row
        FROM brz_exposure
        WHERE
            load_id = p_load_id
            AND NOT EXISTS (
                SELECT 1 FROM slv_rej_exposure r
                WHERE r.load_id = brz_exposure.load_id AND r.src_row = brz_exposure.src_row
            );
        l_inserted := SQL%ROWCOUNT;
        SELECT count(*) INTO l_bronze
        FROM brz_exposure
        WHERE load_id = p_load_id;
        reconcile(p_load_id, l_bronze, l_inserted);
    END insert_exposures;

    PROCEDURE reject_exposures(p_run_id IN NUMBER, p_load_id IN NUMBER, p_cpty_load_id IN NUMBER) IS -- F3
        l_as_of DATE := load_as_of(p_load_id, 'exposure');
        l_as_of_text VARCHAR2(10) := to_char(l_as_of, 'YYYY-MM-DD');
        l_rejected PLS_INTEGER;
    BEGIN
        IF load_as_of(p_cpty_load_id, 'counterparty') != l_as_of THEN
            raise_application_error(c_as_of_mismatch, 'loads ' || p_load_id || ' and ' || p_cpty_load_id || ' differ');
        END IF;
        DELETE FROM slv_rej_exposure
        WHERE load_id = p_load_id;
        INSERT INTO slv_rej_exposure (
            load_id, src_row, as_of_date, reason_code, exposure_id, cpty_id, product_code,
            drawn_amt, undrawn_amt, collateral_amt, collateral_type, currency, raw_as_of_date
        )
        WITH trimmed AS (
            SELECT
                load_id,
                src_row,
                exposure_id,
                cpty_id,
                product_code,
                drawn_amt,
                undrawn_amt,
                collateral_amt,
                collateral_type,
                currency,
                as_of_date,
                trim(exposure_id) AS t_exposure_id,
                trim(cpty_id) AS t_cpty_id,
                trim(product_code) AS t_product_code,
                trim(drawn_amt) AS t_drawn_amt,
                trim(undrawn_amt) AS t_undrawn_amt,
                trim(collateral_amt) AS t_collateral_amt,
                trim(collateral_type) AS t_collateral_type,
                trim(currency) AS t_currency,
                trim(as_of_date) AS t_as_of_date,
                l_as_of_text AS partition_date,
                c_amount AS amount_pattern,
                c_amount_format AS amount_format,
                c_numeric AS numeric_settings
            FROM brz_exposure
            WHERE load_id = p_load_id
        ),

        src AS (
            SELECT
                t.*,
                CASE
                    WHEN regexp_like(t.t_drawn_amt, t.amount_pattern)
                        THEN to_number(t.t_drawn_amt, t.amount_format, t.numeric_settings)
                END AS drawn_value,
                CASE
                    WHEN regexp_like(t.t_undrawn_amt, t.amount_pattern)
                        THEN to_number(t.t_undrawn_amt, t.amount_format, t.numeric_settings)
                END AS undrawn_value,
                CASE
                    WHEN t.t_collateral_amt IS NULL THEN 0
                    WHEN regexp_like(t.t_collateral_amt, t.amount_pattern)
                        THEN to_number(t.t_collateral_amt, t.amount_format, t.numeric_settings)
                END AS collateral_value
            FROM trimmed t
        ),

        accepted_counterparties AS (
            SELECT DISTINCT trim(cpty_id) AS cpty_id
            FROM brz_counterparty
            WHERE
                load_id = p_cpty_load_id
                AND NOT EXISTS (
                    SELECT 1 FROM slv_rej_counterparty r
                    WHERE r.load_id = brz_counterparty.load_id AND r.src_row = brz_counterparty.src_row
                )
        ),

        checked AS (
            SELECT
                s.load_id,
                s.src_row,
                s.exposure_id,
                s.cpty_id,
                s.product_code,
                s.drawn_amt,
                s.undrawn_amt,
                s.collateral_amt,
                s.collateral_type,
                s.currency,
                s.as_of_date,
                CASE
                    WHEN
                        s.t_exposure_id IS NULL OR length(s.t_exposure_id) > 30
                        OR s.t_cpty_id IS NULL OR length(s.t_cpty_id) > 20
                        THEN 'R01'
                    WHEN s.drawn_value IS NULL OR s.undrawn_value IS NULL OR s.collateral_value IS NULL THEN 'R02'
                    WHEN s.drawn_value < 0 OR s.undrawn_value < 0 OR s.collateral_value < 0 THEN 'R03'
                    WHEN NOT EXISTS (
                        SELECT 1 FROM ref_product r
                        WHERE r.product_code = s.t_product_code
                    ) THEN 'R04'
                    WHEN s.t_as_of_date IS NULL OR s.t_as_of_date != s.partition_date THEN 'R05'
                    WHEN count(*) OVER (PARTITION BY s.t_exposure_id) > 1 THEN 'R06'
                    WHEN a.cpty_id IS NULL THEN 'R07'
                    WHEN s.collateral_value > 0 AND s.t_collateral_type IS NULL THEN 'R08'
                    WHEN s.t_collateral_type IS NOT NULL AND NOT EXISTS (
                        SELECT 1 FROM ref_collateral_type r
                        WHERE r.collateral_type = s.t_collateral_type
                    ) THEN 'R09'
                    WHEN
                        (s.t_product_code = 'LOAN' AND s.undrawn_value > 0)
                        OR (s.t_product_code = 'GUARANTEE' AND s.drawn_value > 0)
                        THEN 'R10'
                    WHEN s.t_currency IS NULL OR s.t_currency != 'EUR' THEN 'R11'
                END AS reason_code
            FROM src s
            LEFT JOIN accepted_counterparties a ON s.t_cpty_id = a.cpty_id
        )

        SELECT
            load_id,
            src_row,
            l_as_of,
            reason_code,
            exposure_id,
            cpty_id,
            product_code,
            drawn_amt,
            undrawn_amt,
            collateral_amt,
            collateral_type,
            currency,
            as_of_date
        FROM checked
        WHERE reason_code IS NOT NULL;
        l_rejected := SQL%ROWCOUNT;
        UPDATE ops_load_registry
        SET rows_rejected = l_rejected
        WHERE load_id = p_load_id;
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'reject_exposures');
                RAISE;
    END reject_exposures;

    PROCEDURE replace_as_of(p_run_id IN NUMBER, p_cpty_load_id IN NUMBER, p_expo_load_id IN NUMBER) IS -- F3
        l_as_of DATE := load_as_of(p_cpty_load_id, 'counterparty');
    BEGIN
        IF load_as_of(p_expo_load_id, 'exposure') != l_as_of THEN
            raise_application_error(
                c_as_of_mismatch, 'loads ' || p_cpty_load_id || ' and ' || p_expo_load_id || ' differ'
            );
        END IF;
        DELETE FROM slv_exposure
        WHERE as_of_date = l_as_of;
        DELETE FROM slv_counterparty
        WHERE as_of_date = l_as_of;
        insert_counterparties(p_cpty_load_id, l_as_of);
        insert_exposures(p_expo_load_id, l_as_of);
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'replace_as_of');
                RAISE;
    END replace_as_of;
END pkg_silver;
/
