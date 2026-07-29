ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;

CREATE TABLE brz_counterparty (
    cpty_id VARCHAR2(4000),
    cpty_name VARCHAR2(4000),
    lei VARCHAR2(4000),
    segment_code VARCHAR2(4000),
    country VARCHAR2(4000),
    rating VARCHAR2(4000),
    default_flag VARCHAR2(4000),
    as_of_date VARCHAR2(4000),
    load_id NUMBER(18),
    src_file VARCHAR2(1000),
    src_row NUMBER(10),
    ingested_at TIMESTAMP(6) WITH TIME ZONE
)
PARTITION BY RANGE (load_id)
INTERVAL (1)
(PARTITION p_first VALUES LESS THAN (1));

COMMENT ON TABLE brz_counterparty IS 'Counterparty feed rows as delivered, append-only (F2).';
COMMENT ON COLUMN brz_counterparty.cpty_id IS 'Delivered cpty_id.';
COMMENT ON COLUMN brz_counterparty.cpty_name IS 'Delivered cpty_name.';
COMMENT ON COLUMN brz_counterparty.lei IS 'Delivered lei.';
COMMENT ON COLUMN brz_counterparty.segment_code IS 'Delivered segment_code.';
COMMENT ON COLUMN brz_counterparty.country IS 'Delivered country.';
COMMENT ON COLUMN brz_counterparty.rating IS 'Delivered rating.';
COMMENT ON COLUMN brz_counterparty.default_flag IS 'Delivered default_flag.';
COMMENT ON COLUMN brz_counterparty.as_of_date IS 'Delivered as_of_date.';
COMMENT ON COLUMN brz_counterparty.load_id IS 'Load that inserted the row, see OPS_LOAD_REGISTRY.';
COMMENT ON COLUMN brz_counterparty.src_file IS 'Landing file of the row.';
COMMENT ON COLUMN brz_counterparty.src_row IS '1-based row number in the file.';
COMMENT ON COLUMN brz_counterparty.ingested_at IS 'Ingestion time, UTC, supplied by the loader.';

CREATE TABLE brz_exposure (
    exposure_id VARCHAR2(4000),
    cpty_id VARCHAR2(4000),
    product_code VARCHAR2(4000),
    drawn_amt VARCHAR2(4000),
    undrawn_amt VARCHAR2(4000),
    collateral_amt VARCHAR2(4000),
    collateral_type VARCHAR2(4000),
    currency VARCHAR2(4000),
    as_of_date VARCHAR2(4000),
    load_id NUMBER(18),
    src_file VARCHAR2(1000),
    src_row NUMBER(10),
    ingested_at TIMESTAMP(6) WITH TIME ZONE
)
PARTITION BY RANGE (load_id)
INTERVAL (1)
(PARTITION p_first VALUES LESS THAN (1));

COMMENT ON TABLE brz_exposure IS 'Exposure feed rows as delivered, append-only (F2).';
COMMENT ON COLUMN brz_exposure.exposure_id IS 'Delivered exposure_id.';
COMMENT ON COLUMN brz_exposure.cpty_id IS 'Delivered cpty_id.';
COMMENT ON COLUMN brz_exposure.product_code IS 'Delivered product_code.';
COMMENT ON COLUMN brz_exposure.drawn_amt IS 'Delivered drawn_amt.';
COMMENT ON COLUMN brz_exposure.undrawn_amt IS 'Delivered undrawn_amt.';
COMMENT ON COLUMN brz_exposure.collateral_amt IS 'Delivered collateral_amt.';
COMMENT ON COLUMN brz_exposure.collateral_type IS 'Delivered collateral_type.';
COMMENT ON COLUMN brz_exposure.currency IS 'Delivered currency.';
COMMENT ON COLUMN brz_exposure.as_of_date IS 'Delivered as_of_date.';
COMMENT ON COLUMN brz_exposure.load_id IS 'Load that inserted the row, see OPS_LOAD_REGISTRY.';
COMMENT ON COLUMN brz_exposure.src_file IS 'Landing file of the row.';
COMMENT ON COLUMN brz_exposure.src_row IS '1-based row number in the file.';
COMMENT ON COLUMN brz_exposure.ingested_at IS 'Ingestion time, UTC, supplied by the loader.';
