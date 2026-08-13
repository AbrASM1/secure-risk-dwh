ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY pkg_silver AS
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

    PROCEDURE insert_counterparties(p_run_id IN NUMBER, p_load_id IN NUMBER) IS -- F3
        l_as_of DATE := load_as_of(p_load_id, 'counterparty');
        l_rejected ops_load_registry.rows_rejected%TYPE;
        l_inserted PLS_INTEGER;
        l_bronze PLS_INTEGER;
    BEGIN
        SELECT rows_rejected INTO l_rejected
        FROM ops_load_registry
        WHERE load_id = p_load_id;
        IF l_rejected IS NULL THEN
            raise_application_error(c_rejects_missing, 'rejects of load ' || p_load_id || ' not computed');
        END IF;
        DELETE FROM slv_counterparty
        WHERE as_of_date = l_as_of;
        INSERT INTO slv_counterparty (
            as_of_date, cpty_id, cpty_name, lei, segment_code, country, rating, default_flag, load_id, src_row
        )
        SELECT
            l_as_of,
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
        IF l_bronze != l_inserted + l_rejected THEN
            raise_application_error(
                c_reconciliation,
                'load ' || p_load_id || ': ' || l_bronze || ' bronze rows, '
                || l_inserted || ' silver and ' || l_rejected || ' rejected'
            );
        END IF;
        EXCEPTION
            WHEN OTHERS THEN
                pkg_err.log_error(p_run_id, 'insert_counterparties');
                RAISE;
    END insert_counterparties;
END pkg_silver;
/
