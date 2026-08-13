ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;

CREATE TABLE ref_segment (
    segment_code VARCHAR2 (20 CHAR) NOT NULL,
    lei_required VARCHAR2 (1 CHAR) NOT NULL,
    label VARCHAR2(200) NOT NULL,
    CONSTRAINT ref_segment_pk PRIMARY KEY (segment_code),
    CONSTRAINT ref_segment_lei_required_ck CHECK (lei_required IN ('Y', 'N'))
);

COMMENT ON TABLE ref_segment IS 'Counterparty segments, loaded from db/ref/segment.csv.';
COMMENT ON COLUMN ref_segment.segment_code IS 'Segment code.';
COMMENT ON COLUMN ref_segment.lei_required IS 'Y when an LEI is mandatory for the segment (C06).';
COMMENT ON COLUMN ref_segment.label IS 'Segment label.';

CREATE TABLE ref_rating (
    rating_code VARCHAR2 (20 CHAR) NOT NULL,
    rating_bucket VARCHAR2 (20 CHAR) NOT NULL,
    rating_rank NUMBER(2) NOT NULL,
    CONSTRAINT ref_rating_pk PRIMARY KEY (rating_code),
    CONSTRAINT ref_rating_rating_rank_uk UNIQUE (rating_rank)
);

COMMENT ON TABLE ref_rating IS 'External ratings and their regulatory buckets, loaded from db/ref/rating.csv.';
COMMENT ON COLUMN ref_rating.rating_code IS 'Rating code.';
COMMENT ON COLUMN ref_rating.rating_bucket IS 'Risk-weight bucket of the rating (F5 step 2).';
COMMENT ON COLUMN ref_rating.rating_rank IS 'Order from best to worst, used for one-notch migrations.';

CREATE TABLE ref_product (
    product_code VARCHAR2 (20 CHAR) NOT NULL,
    product_type VARCHAR2 (20 CHAR) NOT NULL,
    label VARCHAR2(200) NOT NULL,
    CONSTRAINT ref_product_pk PRIMARY KEY (product_code),
    CONSTRAINT ref_product_product_type_ck CHECK (product_type IN ('ON_BALANCE', 'OFF_BALANCE'))
);

COMMENT ON TABLE ref_product IS 'Exposure products, loaded from db/ref/product.csv.';
COMMENT ON COLUMN ref_product.product_code IS 'Product code.';
COMMENT ON COLUMN ref_product.product_type IS 'ON_BALANCE or OFF_BALANCE.';
COMMENT ON COLUMN ref_product.label IS 'Product label.';

CREATE TABLE ref_collateral_type (
    collateral_type VARCHAR2 (20 CHAR) NOT NULL,
    label VARCHAR2(200) NOT NULL,
    CONSTRAINT ref_collateral_type_pk PRIMARY KEY (collateral_type)
);

COMMENT ON TABLE ref_collateral_type IS 'Financial collateral types, loaded from db/ref/collateral_type.csv.';
COMMENT ON COLUMN ref_collateral_type.collateral_type IS 'Collateral type code.';
COMMENT ON COLUMN ref_collateral_type.label IS 'Collateral type label.';

CREATE TABLE ref_country (
    country_code VARCHAR2 (2 CHAR) NOT NULL,
    label VARCHAR2(200) NOT NULL,
    CONSTRAINT ref_country_pk PRIMARY KEY (country_code)
);

COMMENT ON TABLE ref_country IS 'ISO 3166-1 alpha-2 countries, loaded from db/ref/country.csv.';
COMMENT ON COLUMN ref_country.country_code IS 'Country code.';
COMMENT ON COLUMN ref_country.label IS 'Country name.';

CREATE TABLE ref_reason_code (
    reason_code VARCHAR2 (3 CHAR) NOT NULL,
    feed VARCHAR2(20) NOT NULL,
    rule_text VARCHAR2(4000) NOT NULL,
    CONSTRAINT ref_reason_code_pk PRIMARY KEY (reason_code),
    CONSTRAINT ref_reason_code_feed_ck CHECK (feed IN ('counterparty', 'exposure'))
);

COMMENT ON TABLE ref_reason_code IS 'Reject reason codes and their rule text, loaded from db/ref/reason_code.csv.';
COMMENT ON COLUMN ref_reason_code.reason_code IS 'Rule code; code order is evaluation order.';
COMMENT ON COLUMN ref_reason_code.feed IS 'Feed the rule applies to.';
COMMENT ON COLUMN ref_reason_code.rule_text IS 'Rule statement from SPEC section 5.';

CREATE DIRECTORY srdwh_ref_dir AS '/opt/srdwh/ref';
GRANT READ ON DIRECTORY srdwh_ref_dir TO srdwh_owner;

DECLARE
    PROCEDURE create_external(p_table IN VARCHAR2, p_columns IN VARCHAR2, p_file IN VARCHAR2) IS
    BEGIN
        EXECUTE IMMEDIATE 'CREATE TABLE ' || p_table || ' (' || p_columns || ') '
            || 'ORGANIZATION EXTERNAL (TYPE oracle_loader DEFAULT DIRECTORY srdwh_ref_dir ACCESS PARAMETERS ('
            || 'RECORDS DELIMITED BY NEWLINE CHARACTERSET al32utf8 SKIP 1 NOBADFILE NODISCARDFILE NOLOGFILE '
            || 'FIELDS CSV WITHOUT EMBEDDED NOTRIM MISSING FIELD VALUES ARE NULL) '
            || 'LOCATION (''' || p_file || ''')) REJECT LIMIT 0';
    END create_external;
BEGIN
    create_external('ext_segment', 'segment_code VARCHAR2(20), lei_required VARCHAR2(1), label VARCHAR2(200)', 'segment.csv');
    create_external('ext_rating', 'rating_code VARCHAR2(20), rating_bucket VARCHAR2(20), rating_rank VARCHAR2(2)', 'rating.csv');
    create_external('ext_product', 'product_code VARCHAR2(20), product_type VARCHAR2(20), label VARCHAR2(200)', 'product.csv');
    create_external('ext_collateral_type', 'collateral_type VARCHAR2(20), label VARCHAR2(200)', 'collateral_type.csv');
    create_external('ext_country', 'country_code VARCHAR2(2), label VARCHAR2(200)', 'country.csv');
    create_external('ext_reason_code', 'reason_code VARCHAR2(3), feed VARCHAR2(20), rule_text VARCHAR2(4000)', 'reason_code.csv');
END;
/

INSERT INTO ref_segment (segment_code, lei_required, label)
SELECT segment_code, lei_required, label FROM ext_segment;
INSERT INTO ref_rating (rating_code, rating_bucket, rating_rank)
SELECT rating_code, rating_bucket, TO_NUMBER(rating_rank) FROM ext_rating;
INSERT INTO ref_product (product_code, product_type, label)
SELECT product_code, product_type, label FROM ext_product;
INSERT INTO ref_collateral_type (collateral_type, label)
SELECT collateral_type, label FROM ext_collateral_type;
INSERT INTO ref_country (country_code, label)
SELECT country_code, label FROM ext_country;
INSERT INTO ref_reason_code (reason_code, feed, rule_text)
SELECT reason_code, feed, rule_text FROM ext_reason_code;
COMMIT;

DROP TABLE ext_segment PURGE;
DROP TABLE ext_rating PURGE;
DROP TABLE ext_product PURGE;
DROP TABLE ext_collateral_type PURGE;
DROP TABLE ext_country PURGE;
DROP TABLE ext_reason_code PURGE;
DROP DIRECTORY srdwh_ref_dir;
