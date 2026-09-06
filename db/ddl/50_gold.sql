ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;

CREATE TABLE gld_dim_date (
    date_sk NUMBER(8) NOT NULL,
    calendar_date DATE NOT NULL,
    month_no NUMBER(2) NOT NULL,
    quarter_no NUMBER(1) NOT NULL,
    year_no NUMBER(4) NOT NULL,
    is_month_end VARCHAR2 (1 CHAR) NOT NULL,
    CONSTRAINT gld_dim_date_pk PRIMARY KEY (date_sk) RELY,
    CONSTRAINT gld_dim_date_calendar_date_uk UNIQUE (calendar_date),
    CONSTRAINT gld_dim_date_is_month_end_ck CHECK (is_month_end IN ('Y', 'N'))
);

COMMENT ON TABLE gld_dim_date
IS 'Calendar dimension, one row per day from 2000-01-01 to 2040-12-31, seeded at deploy (F4).';
COMMENT ON COLUMN gld_dim_date.date_sk IS 'Date key YYYYMMDD.';
COMMENT ON COLUMN gld_dim_date.calendar_date IS 'Calendar date.';
COMMENT ON COLUMN gld_dim_date.month_no IS 'Month number.';
COMMENT ON COLUMN gld_dim_date.quarter_no IS 'Quarter number.';
COMMENT ON COLUMN gld_dim_date.year_no IS 'Calendar year.';
COMMENT ON COLUMN gld_dim_date.is_month_end IS 'Y on the last day of the month.';

CREATE TABLE gld_dim_product (
    product_sk NUMBER(18) GENERATED ALWAYS AS IDENTITY,
    product_code VARCHAR2 (20 CHAR) NOT NULL,
    product_type VARCHAR2 (20 CHAR) NOT NULL,
    CONSTRAINT gld_dim_product_pk PRIMARY KEY (product_sk) RELY,
    CONSTRAINT gld_dim_product_product_code_uk UNIQUE (product_code)
);

COMMENT ON TABLE gld_dim_product IS 'Product dimension, from REF_PRODUCT, seeded at deploy (F4).';
COMMENT ON COLUMN gld_dim_product.product_sk IS 'Product surrogate key.';
COMMENT ON COLUMN gld_dim_product.product_code IS 'Product code.';
COMMENT ON COLUMN gld_dim_product.product_type IS 'ON_BALANCE or OFF_BALANCE.';

CREATE TABLE gld_dim_counterparty (
    cpty_sk NUMBER(18) GENERATED ALWAYS AS IDENTITY,
    cpty_id VARCHAR2 (20 CHAR) NOT NULL,
    segment_code VARCHAR2 (20 CHAR) NOT NULL,
    rating VARCHAR2 (20 CHAR) NOT NULL,
    default_flag VARCHAR2 (1 CHAR) NOT NULL,
    cpty_name VARCHAR2 (200 CHAR) NOT NULL,
    lei VARCHAR2 (20 CHAR),
    country VARCHAR2 (2 CHAR) NOT NULL,
    valid_from DATE NOT NULL,
    valid_to DATE NOT NULL,
    is_current VARCHAR2 (1 CHAR) NOT NULL,
    CONSTRAINT gld_dim_counterparty_pk PRIMARY KEY (cpty_sk) RELY,
    CONSTRAINT gld_dim_counterparty_cpty_id_valid_from_uk UNIQUE (cpty_id, valid_from),
    CONSTRAINT gld_dim_counterparty_default_flag_ck CHECK (default_flag IN ('Y', 'N')),
    CONSTRAINT gld_dim_counterparty_is_current_ck CHECK (is_current IN ('Y', 'N')),
    CONSTRAINT gld_dim_counterparty_validity_ck CHECK (valid_from < valid_to),
    CONSTRAINT gld_dim_counterparty_current_ck CHECK (
        (is_current = 'Y' AND valid_to = DATE '9999-12-31')
        OR (is_current = 'N' AND valid_to < DATE '9999-12-31')
    )
);

CREATE UNIQUE INDEX gld_dim_counterparty_current_ux
ON gld_dim_counterparty (CASE is_current WHEN 'Y' THEN cpty_id END);

COMMENT ON TABLE gld_dim_counterparty
IS 'Counterparty dimension: SCD2 on segment_code, rating and default_flag, SCD1 on cpty_name, lei and country (F4).';
COMMENT ON COLUMN gld_dim_counterparty.cpty_sk IS 'Counterparty version surrogate key.';
COMMENT ON COLUMN gld_dim_counterparty.cpty_id IS 'Counterparty identifier.';
COMMENT ON COLUMN gld_dim_counterparty.segment_code IS 'Segment, SCD2.';
COMMENT ON COLUMN gld_dim_counterparty.rating IS 'External rating, SCD2.';
COMMENT ON COLUMN gld_dim_counterparty.default_flag IS 'Default flag, SCD2.';
COMMENT ON COLUMN gld_dim_counterparty.cpty_name
IS 'Counterparty name, SCD1, redacted outside pipeline and R_RISK_MANAGER.';
COMMENT ON COLUMN gld_dim_counterparty.lei IS 'LEI, SCD1, redacted outside pipeline and R_RISK_MANAGER.';
COMMENT ON COLUMN gld_dim_counterparty.country IS 'Country, SCD1.';
COMMENT ON COLUMN gld_dim_counterparty.valid_from IS 'First as_of of the version, inclusive.';
COMMENT ON COLUMN gld_dim_counterparty.valid_to IS 'End of the version, exclusive; 9999-12-31 when open.';
COMMENT ON COLUMN gld_dim_counterparty.is_current IS 'Y for the open version.';

CREATE TABLE gld_fact_exposure (
    as_of_date DATE NOT NULL,
    date_sk NUMBER(8) NOT NULL,
    cpty_sk NUMBER(18) NOT NULL,
    product_sk NUMBER(18) NOT NULL,
    segment_code VARCHAR2 (20 CHAR) NOT NULL,
    exposure_id VARCHAR2 (30 CHAR) NOT NULL,
    drawn_amt NUMBER(18,2) NOT NULL,
    undrawn_amt NUMBER(18,2) NOT NULL,
    collateral_amt NUMBER(18,2) NOT NULL,
    collateral_type VARCHAR2 (20 CHAR),
    run_id NUMBER(18) NOT NULL,
    CONSTRAINT gld_fact_exposure_pk PRIMARY KEY (as_of_date, exposure_id) RELY USING INDEX LOCAL,
    CONSTRAINT gld_fact_exposure_date_sk_fk FOREIGN KEY (date_sk)
        REFERENCES gld_dim_date (date_sk) RELY DISABLE NOVALIDATE,
    CONSTRAINT gld_fact_exposure_cpty_sk_fk FOREIGN KEY (cpty_sk)
        REFERENCES gld_dim_counterparty (cpty_sk) RELY DISABLE NOVALIDATE,
    CONSTRAINT gld_fact_exposure_product_sk_fk FOREIGN KEY (product_sk)
        REFERENCES gld_dim_product (product_sk) RELY DISABLE NOVALIDATE
)
PARTITION BY RANGE (as_of_date)
INTERVAL (NUMTOYMINTERVAL(1, 'MONTH'))
(PARTITION p_first VALUES LESS THAN (DATE '2000-02-01'));

CREATE BITMAP INDEX gld_fact_exposure_date_sk_bx ON gld_fact_exposure (date_sk) LOCAL;
CREATE BITMAP INDEX gld_fact_exposure_cpty_sk_bx ON gld_fact_exposure (cpty_sk) LOCAL;
CREATE BITMAP INDEX gld_fact_exposure_product_sk_bx ON gld_fact_exposure (product_sk) LOCAL;
CREATE BITMAP INDEX gld_fact_exposure_segment_code_bx ON gld_fact_exposure (segment_code) LOCAL;

COMMENT ON TABLE gld_fact_exposure IS 'Monthly periodic snapshot, one row per exposure and as_of; amounts add across exposures, never across as_of (F4).';
COMMENT ON COLUMN gld_fact_exposure.as_of_date IS 'As-of date.';
COMMENT ON COLUMN gld_fact_exposure.date_sk IS 'Date key of as_of_date.';
COMMENT ON COLUMN gld_fact_exposure.cpty_sk IS 'Counterparty version valid at as_of_date.';
COMMENT ON COLUMN gld_fact_exposure.product_sk IS 'Product.';
COMMENT ON COLUMN gld_fact_exposure.segment_code IS 'Segment of the counterparty version, denormalised for VPD.';
COMMENT ON COLUMN gld_fact_exposure.exposure_id IS 'Exposure identifier.';
COMMENT ON COLUMN gld_fact_exposure.drawn_amt IS 'Drawn amount, EUR.';
COMMENT ON COLUMN gld_fact_exposure.undrawn_amt IS 'Undrawn amount, EUR.';
COMMENT ON COLUMN gld_fact_exposure.collateral_amt IS 'Collateral amount, EUR.';
COMMENT ON COLUMN gld_fact_exposure.collateral_type IS 'Collateral type, empty without collateral.';
COMMENT ON COLUMN gld_fact_exposure.run_id IS 'Run that wrote the row.';

CREATE TABLE gld_fact_rwa (
    as_of_date DATE NOT NULL,
    date_sk NUMBER(8) NOT NULL,
    cpty_sk NUMBER(18) NOT NULL,
    product_sk NUMBER(18) NOT NULL,
    segment_code VARCHAR2 (20 CHAR) NOT NULL,
    exposure_id VARCHAR2 (30 CHAR) NOT NULL,
    exposure_class VARCHAR2 (20 CHAR) NOT NULL,
    rating_bucket VARCHAR2 (20 CHAR) NOT NULL,
    ccf NUMBER(5,4) NOT NULL,
    ead NUMBER(30,6) NOT NULL,
    hc NUMBER(5,4) NOT NULL,
    e_star NUMBER(30,6) NOT NULL,
    risk_weight NUMBER(6,4) NOT NULL,
    rwa NUMBER(20,2) NOT NULL,
    param_version NUMBER(4) NOT NULL,
    run_id NUMBER(18) NOT NULL,
    CONSTRAINT gld_fact_rwa_pk PRIMARY KEY (as_of_date, exposure_id) USING INDEX LOCAL,
    CONSTRAINT gld_fact_rwa_as_of_date_exposure_id_fk FOREIGN KEY (as_of_date, exposure_id)
        REFERENCES gld_fact_exposure (as_of_date, exposure_id) RELY DISABLE NOVALIDATE,
    CONSTRAINT gld_fact_rwa_date_sk_fk FOREIGN KEY (date_sk)
        REFERENCES gld_dim_date (date_sk) RELY DISABLE NOVALIDATE,
    CONSTRAINT gld_fact_rwa_cpty_sk_fk FOREIGN KEY (cpty_sk)
        REFERENCES gld_dim_counterparty (cpty_sk) RELY DISABLE NOVALIDATE,
    CONSTRAINT gld_fact_rwa_product_sk_fk FOREIGN KEY (product_sk)
        REFERENCES gld_dim_product (product_sk) RELY DISABLE NOVALIDATE
)
PARTITION BY RANGE (as_of_date)
INTERVAL (NUMTOYMINTERVAL(1, 'MONTH'))
(PARTITION p_first VALUES LESS THAN (DATE '2000-02-01'));

CREATE BITMAP INDEX gld_fact_rwa_date_sk_bx ON gld_fact_rwa (date_sk) LOCAL;
CREATE BITMAP INDEX gld_fact_rwa_cpty_sk_bx ON gld_fact_rwa (cpty_sk) LOCAL;
CREATE BITMAP INDEX gld_fact_rwa_product_sk_bx ON gld_fact_rwa (product_sk) LOCAL;
CREATE BITMAP INDEX gld_fact_rwa_segment_code_bx ON gld_fact_rwa (segment_code) LOCAL;

COMMENT ON TABLE gld_fact_rwa IS 'Standardised credit RWA per exposure and as_of, same grain and keys as GLD_FACT_EXPOSURE (F5).';
COMMENT ON COLUMN gld_fact_rwa.as_of_date IS 'As-of date.';
COMMENT ON COLUMN gld_fact_rwa.date_sk IS 'Date key of as_of_date.';
COMMENT ON COLUMN gld_fact_rwa.cpty_sk IS 'Counterparty version valid at as_of_date.';
COMMENT ON COLUMN gld_fact_rwa.product_sk IS 'Product.';
COMMENT ON COLUMN gld_fact_rwa.segment_code IS 'Segment, denormalised for VPD.';
COMMENT ON COLUMN gld_fact_rwa.exposure_id IS 'Exposure identifier.';
COMMENT ON COLUMN gld_fact_rwa.exposure_class IS 'DEFAULTED when default_flag = Y, else segment_code.';
COMMENT ON COLUMN gld_fact_rwa.rating_bucket IS 'Rating bucket from REF_RATING.';
COMMENT ON COLUMN gld_fact_rwa.ccf IS 'Credit conversion factor of the product.';
COMMENT ON COLUMN gld_fact_rwa.ead IS 'drawn_amt + ccf x undrawn_amt, unrounded.';
COMMENT ON COLUMN gld_fact_rwa.hc IS 'Haircut of the collateral type, 0 without collateral.';
COMMENT ON COLUMN gld_fact_rwa.e_star IS 'Exposure after credit risk mitigation, unrounded.';
COMMENT ON COLUMN gld_fact_rwa.risk_weight IS 'Risk weight of exposure_class and rating_bucket.';
COMMENT ON COLUMN gld_fact_rwa.rwa IS 'ROUND(e_star x risk_weight, 2).';
COMMENT ON COLUMN gld_fact_rwa.param_version IS 'Parameter set valid at as_of_date.';
COMMENT ON COLUMN gld_fact_rwa.run_id IS 'Run that wrote the row.';

CREATE TABLE gld_mart_rwa (
    as_of_date DATE NOT NULL,
    segment_code VARCHAR2 (20 CHAR) NOT NULL,
    exposure_class VARCHAR2 (20 CHAR) NOT NULL,
    risk_weight NUMBER(6,4) NOT NULL,
    n_exposures NUMBER(10) NOT NULL,
    ead NUMBER(30,6) NOT NULL,
    e_star NUMBER(30,6) NOT NULL,
    rwa NUMBER(28,2) NOT NULL,
    CONSTRAINT gld_mart_rwa_pk PRIMARY KEY (as_of_date, segment_code, exposure_class, risk_weight)
);

COMMENT ON TABLE gld_mart_rwa IS 'RWA aggregated per as_of, segment, exposure class and risk weight (F4).';
COMMENT ON COLUMN gld_mart_rwa.as_of_date IS 'As-of date.';
COMMENT ON COLUMN gld_mart_rwa.segment_code IS 'Segment.';
COMMENT ON COLUMN gld_mart_rwa.exposure_class IS 'Exposure class.';
COMMENT ON COLUMN gld_mart_rwa.risk_weight IS 'Risk weight.';
COMMENT ON COLUMN gld_mart_rwa.n_exposures IS 'Number of exposures.';
COMMENT ON COLUMN gld_mart_rwa.ead IS 'Sum of ead.';
COMMENT ON COLUMN gld_mart_rwa.e_star IS 'Sum of e_star.';
COMMENT ON COLUMN gld_mart_rwa.rwa IS 'Sum of rwa.';

INSERT INTO gld_dim_date (date_sk, calendar_date, month_no, quarter_no, year_no, is_month_end)
SELECT
    to_number(to_char(d.calendar_date, 'YYYYMMDD')) AS date_sk,
    d.calendar_date,
    extract(MONTH FROM d.calendar_date) AS month_no,
    to_number(to_char(d.calendar_date, 'Q')) AS quarter_no,
    extract(YEAR FROM d.calendar_date) AS year_no,
    CASE WHEN d.calendar_date = last_day(d.calendar_date) THEN 'Y' ELSE 'N' END AS is_month_end
FROM (
    SELECT DATE '2000-01-01' + LEVEL - 1 AS calendar_date FROM dual
    CONNECT BY LEVEL <= DATE '2040-12-31' - DATE '2000-01-01' + 1
) d;

INSERT INTO gld_dim_product (product_code, product_type)
SELECT product_code, product_type FROM ref_product;
COMMIT;
