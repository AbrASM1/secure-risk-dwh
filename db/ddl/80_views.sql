ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;

CREATE OR REPLACE VIEW v_rwa_by_class AS
SELECT
    as_of_date,
    exposure_class,
    risk_weight,
    cast(sum(n_exposures) AS NUMBER(10)) AS n_exposures,
    cast(sum(e_star) AS NUMBER(30, 6)) AS exposure_value,
    cast(sum(rwa) AS NUMBER(28, 2)) AS rwea
FROM gld_mart_rwa
GROUP BY as_of_date, exposure_class, risk_weight;

COMMENT ON TABLE v_rwa_by_class
IS 'RWA per as_of, exposure class and risk weight: COREP C 07.00 risk-weight breakdown, v1 subset (F6).';
COMMENT ON COLUMN v_rwa_by_class.as_of_date IS 'As-of date.';
COMMENT ON COLUMN v_rwa_by_class.exposure_class IS 'Exposure class.';
COMMENT ON COLUMN v_rwa_by_class.risk_weight IS 'Risk weight.';
COMMENT ON COLUMN v_rwa_by_class.n_exposures IS 'Number of exposures.';
COMMENT ON COLUMN v_rwa_by_class.exposure_value IS 'SUM(e_star).';
COMMENT ON COLUMN v_rwa_by_class.rwea IS 'SUM(rwa), risk-weighted exposure amount.';

CREATE OR REPLACE VIEW v_rwa_trend AS
WITH segments AS (
    SELECT
        as_of_date,
        segment_code,
        sum(ead) AS ead,
        sum(rwa) AS rwa,
        row_number() OVER (PARTITION BY segment_code ORDER BY as_of_date DESC) AS recency
    FROM gld_mart_rwa
    GROUP BY as_of_date, segment_code
)

SELECT
    as_of_date,
    segment_code,
    cast(ead AS NUMBER(30, 6)) AS ead,
    cast(rwa AS NUMBER(28, 2)) AS rwa,
    cast(rwa / nullif(ead, 0) AS NUMBER(30, 6)) AS rwa_density
FROM segments
WHERE recency <= 12;

COMMENT ON TABLE v_rwa_trend IS 'EAD, RWA and RWA density per segment over the last 12 as_of (F6).';
COMMENT ON COLUMN v_rwa_trend.as_of_date IS 'As-of date.';
COMMENT ON COLUMN v_rwa_trend.segment_code IS 'Segment.';
COMMENT ON COLUMN v_rwa_trend.ead IS 'SUM(ead).';
COMMENT ON COLUMN v_rwa_trend.rwa IS 'SUM(rwa).';
COMMENT ON COLUMN v_rwa_trend.rwa_density IS 'SUM(rwa) / NULLIF(SUM(ead), 0).';

CREATE OR REPLACE VIEW v_top_exposures AS
WITH ranked AS (
    SELECT
        r.as_of_date,
        r.exposure_id,
        c.cpty_id,
        r.segment_code,
        r.exposure_class,
        r.ead,
        r.rwa,
        row_number() OVER (PARTITION BY r.as_of_date ORDER BY r.rwa DESC, r.exposure_id ASC) AS top_rank
    FROM gld_fact_rwa r
    INNER JOIN gld_dim_counterparty c ON r.cpty_sk = c.cpty_sk
)

SELECT
    as_of_date,
    exposure_id,
    cpty_id,
    segment_code,
    exposure_class,
    ead,
    rwa
FROM ranked
WHERE top_rank <= 20;

COMMENT ON TABLE v_top_exposures IS 'Top 20 exposures by rwa per as_of, ties broken by exposure_id (F6).';
COMMENT ON COLUMN v_top_exposures.as_of_date IS 'As-of date.';
COMMENT ON COLUMN v_top_exposures.exposure_id IS 'Exposure identifier.';
COMMENT ON COLUMN v_top_exposures.cpty_id IS 'Counterparty identifier.';
COMMENT ON COLUMN v_top_exposures.segment_code IS 'Segment.';
COMMENT ON COLUMN v_top_exposures.exposure_class IS 'Exposure class.';
COMMENT ON COLUMN v_top_exposures.ead IS 'Exposure at default.';
COMMENT ON COLUMN v_top_exposures.rwa IS 'Risk-weighted asset.';
