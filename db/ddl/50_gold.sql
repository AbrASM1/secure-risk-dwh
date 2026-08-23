ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;

CREATE TABLE gld_dim_date (
    date_sk NUMBER(8) NOT NULL,
    calendar_date DATE NOT NULL,
    month_no NUMBER(2) NOT NULL,
    quarter_no NUMBER(1) NOT NULL,
    year_no NUMBER(4) NOT NULL,
    is_month_end VARCHAR2 (1 CHAR) NOT NULL,
    CONSTRAINT gld_dim_date_pk PRIMARY KEY (date_sk),
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
    CONSTRAINT gld_dim_product_pk PRIMARY KEY (product_sk),
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
    CONSTRAINT gld_dim_counterparty_pk PRIMARY KEY (cpty_sk),
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
