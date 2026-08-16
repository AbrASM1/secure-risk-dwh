ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;

CREATE TABLE slv_counterparty (
    as_of_date DATE NOT NULL,
    cpty_id VARCHAR2 (20 CHAR) NOT NULL,
    cpty_name VARCHAR2 (200 CHAR) NOT NULL,
    lei VARCHAR2 (20 CHAR),
    segment_code VARCHAR2 (20 CHAR) NOT NULL,
    country VARCHAR2 (2 CHAR) NOT NULL,
    rating VARCHAR2 (20 CHAR) NOT NULL,
    default_flag VARCHAR2 (1 CHAR) NOT NULL,
    load_id NUMBER(18) NOT NULL,
    src_row NUMBER(10) NOT NULL,
    CONSTRAINT slv_counterparty_pk PRIMARY KEY (as_of_date, cpty_id) USING INDEX LOCAL,
    CONSTRAINT slv_counterparty_default_flag_ck CHECK (default_flag IN ('Y', 'N')),
    CONSTRAINT slv_counterparty_segment_code_fk FOREIGN KEY (segment_code) REFERENCES ref_segment (segment_code),
    CONSTRAINT slv_counterparty_country_fk FOREIGN KEY (country) REFERENCES ref_country (country_code),
    CONSTRAINT slv_counterparty_rating_fk FOREIGN KEY (rating) REFERENCES ref_rating (rating_code)
)
PARTITION BY RANGE (as_of_date)
INTERVAL (NUMTOYMINTERVAL(1, 'MONTH'))
(PARTITION p_first VALUES LESS THAN (DATE '2000-02-01'));

COMMENT ON TABLE slv_counterparty IS 'Validated counterparties per as_of, typed (F3).';
COMMENT ON COLUMN slv_counterparty.as_of_date IS 'As-of date.';
COMMENT ON COLUMN slv_counterparty.cpty_id IS 'Counterparty identifier.';
COMMENT ON COLUMN slv_counterparty.cpty_name IS 'Counterparty name.';
COMMENT ON COLUMN slv_counterparty.lei IS 'LEI, mandatory when REF_SEGMENT.lei_required = Y.';
COMMENT ON COLUMN slv_counterparty.segment_code IS 'Segment.';
COMMENT ON COLUMN slv_counterparty.country IS 'Country.';
COMMENT ON COLUMN slv_counterparty.rating IS 'External rating.';
COMMENT ON COLUMN slv_counterparty.default_flag IS 'Y when the counterparty is in default.';
COMMENT ON COLUMN slv_counterparty.load_id IS 'Bronze load of the row.';
COMMENT ON COLUMN slv_counterparty.src_row IS 'Row number in the landing file of load_id.';

CREATE TABLE slv_rej_counterparty (
    load_id NUMBER(18) NOT NULL,
    src_row NUMBER(10) NOT NULL,
    as_of_date DATE NOT NULL,
    reason_code VARCHAR2 (3 CHAR) NOT NULL,
    cpty_id VARCHAR2(4000),
    cpty_name VARCHAR2(4000),
    lei VARCHAR2(4000),
    segment_code VARCHAR2(4000),
    country VARCHAR2(4000),
    rating VARCHAR2(4000),
    default_flag VARCHAR2(4000),
    raw_as_of_date VARCHAR2(4000),
    CONSTRAINT slv_rej_counterparty_pk PRIMARY KEY (load_id, src_row),
    CONSTRAINT slv_rej_counterparty_load_id_fk FOREIGN KEY (load_id) REFERENCES ops_load_registry (load_id),
    CONSTRAINT slv_rej_counterparty_reason_code_fk FOREIGN KEY (reason_code) REFERENCES ref_reason_code (reason_code)
);

COMMENT ON TABLE slv_rej_counterparty IS 'Rejected counterparty rows with the first failing rule, replaced per load_id (F3).';
COMMENT ON COLUMN slv_rej_counterparty.load_id IS 'Bronze load of the row.';
COMMENT ON COLUMN slv_rej_counterparty.src_row IS 'Row number in the landing file.';
COMMENT ON COLUMN slv_rej_counterparty.as_of_date IS 'As-of date of the file partition.';
COMMENT ON COLUMN slv_rej_counterparty.reason_code IS 'First failing rule.';
COMMENT ON COLUMN slv_rej_counterparty.cpty_id IS 'Delivered cpty_id.';
COMMENT ON COLUMN slv_rej_counterparty.cpty_name IS 'Delivered cpty_name.';
COMMENT ON COLUMN slv_rej_counterparty.lei IS 'Delivered lei.';
COMMENT ON COLUMN slv_rej_counterparty.segment_code IS 'Delivered segment_code.';
COMMENT ON COLUMN slv_rej_counterparty.country IS 'Delivered country.';
COMMENT ON COLUMN slv_rej_counterparty.rating IS 'Delivered rating.';
COMMENT ON COLUMN slv_rej_counterparty.default_flag IS 'Delivered default_flag.';
COMMENT ON COLUMN slv_rej_counterparty.raw_as_of_date IS 'Delivered as_of_date.';

CREATE TABLE slv_exposure (
    as_of_date DATE NOT NULL,
    exposure_id VARCHAR2 (30 CHAR) NOT NULL,
    cpty_id VARCHAR2 (20 CHAR) NOT NULL,
    product_code VARCHAR2 (20 CHAR) NOT NULL,
    drawn_amt NUMBER(18,2) NOT NULL,
    undrawn_amt NUMBER(18,2) NOT NULL,
    collateral_amt NUMBER(18,2) NOT NULL,
    collateral_type VARCHAR2 (20 CHAR),
    currency VARCHAR2 (3 CHAR) NOT NULL,
    load_id NUMBER(18) NOT NULL,
    src_row NUMBER(10) NOT NULL,
    CONSTRAINT slv_exposure_pk PRIMARY KEY (as_of_date, exposure_id) USING INDEX LOCAL,
    CONSTRAINT slv_exposure_amounts_ck CHECK (drawn_amt >= 0 AND undrawn_amt >= 0 AND collateral_amt >= 0),
    CONSTRAINT slv_exposure_as_of_date_cpty_id_fk FOREIGN KEY (as_of_date, cpty_id) REFERENCES slv_counterparty (as_of_date, cpty_id),
    CONSTRAINT slv_exposure_product_code_fk FOREIGN KEY (product_code) REFERENCES ref_product (product_code),
    CONSTRAINT slv_exposure_collateral_type_fk FOREIGN KEY (collateral_type) REFERENCES ref_collateral_type (collateral_type)
)
PARTITION BY RANGE (as_of_date)
INTERVAL (NUMTOYMINTERVAL(1, 'MONTH'))
(PARTITION p_first VALUES LESS THAN (DATE '2000-02-01'));

CREATE INDEX slv_exposure_as_of_date_cpty_id_ix ON slv_exposure (as_of_date, cpty_id) LOCAL;

COMMENT ON TABLE slv_exposure IS 'Validated exposures per as_of, typed (F3).';
COMMENT ON COLUMN slv_exposure.as_of_date IS 'As-of date.';
COMMENT ON COLUMN slv_exposure.exposure_id IS 'Exposure identifier.';
COMMENT ON COLUMN slv_exposure.cpty_id IS 'Counterparty of the exposure.';
COMMENT ON COLUMN slv_exposure.product_code IS 'Product.';
COMMENT ON COLUMN slv_exposure.drawn_amt IS 'Drawn amount, EUR.';
COMMENT ON COLUMN slv_exposure.undrawn_amt IS 'Undrawn amount, EUR.';
COMMENT ON COLUMN slv_exposure.collateral_amt IS 'Collateral amount, EUR; 0 when delivered empty.';
COMMENT ON COLUMN slv_exposure.collateral_type IS 'Collateral type, empty without collateral.';
COMMENT ON COLUMN slv_exposure.currency IS 'Currency, EUR only (R11).';
COMMENT ON COLUMN slv_exposure.load_id IS 'Bronze load of the row.';
COMMENT ON COLUMN slv_exposure.src_row IS 'Row number in the landing file of load_id.';

CREATE TABLE slv_rej_exposure (
    load_id NUMBER(18) NOT NULL,
    src_row NUMBER(10) NOT NULL,
    as_of_date DATE NOT NULL,
    reason_code VARCHAR2 (3 CHAR) NOT NULL,
    exposure_id VARCHAR2(4000),
    cpty_id VARCHAR2(4000),
    product_code VARCHAR2(4000),
    drawn_amt VARCHAR2(4000),
    undrawn_amt VARCHAR2(4000),
    collateral_amt VARCHAR2(4000),
    collateral_type VARCHAR2(4000),
    currency VARCHAR2(4000),
    raw_as_of_date VARCHAR2(4000),
    CONSTRAINT slv_rej_exposure_pk PRIMARY KEY (load_id, src_row),
    CONSTRAINT slv_rej_exposure_load_id_fk FOREIGN KEY (load_id) REFERENCES ops_load_registry (load_id),
    CONSTRAINT slv_rej_exposure_reason_code_fk FOREIGN KEY (reason_code) REFERENCES ref_reason_code (reason_code)
);

COMMENT ON TABLE slv_rej_exposure IS 'Rejected exposure rows with the first failing rule, replaced per load_id (F3).';
COMMENT ON COLUMN slv_rej_exposure.load_id IS 'Bronze load of the row.';
COMMENT ON COLUMN slv_rej_exposure.src_row IS 'Row number in the landing file.';
COMMENT ON COLUMN slv_rej_exposure.as_of_date IS 'As-of date of the file partition.';
COMMENT ON COLUMN slv_rej_exposure.reason_code IS 'First failing rule.';
COMMENT ON COLUMN slv_rej_exposure.exposure_id IS 'Delivered exposure_id.';
COMMENT ON COLUMN slv_rej_exposure.cpty_id IS 'Delivered cpty_id.';
COMMENT ON COLUMN slv_rej_exposure.product_code IS 'Delivered product_code.';
COMMENT ON COLUMN slv_rej_exposure.drawn_amt IS 'Delivered drawn_amt.';
COMMENT ON COLUMN slv_rej_exposure.undrawn_amt IS 'Delivered undrawn_amt.';
COMMENT ON COLUMN slv_rej_exposure.collateral_amt IS 'Delivered collateral_amt.';
COMMENT ON COLUMN slv_rej_exposure.collateral_type IS 'Delivered collateral_type.';
COMMENT ON COLUMN slv_rej_exposure.currency IS 'Delivered currency.';
COMMENT ON COLUMN slv_rej_exposure.raw_as_of_date IS 'Delivered as_of_date.';
