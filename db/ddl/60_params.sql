ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;

CREATE TABLE param_ccf (
    param_version NUMBER(4) NOT NULL,
    product_code VARCHAR2 (20 CHAR) NOT NULL,
    ccf NUMBER(5, 4) NOT NULL,
    valid_from DATE NOT NULL,
    valid_to DATE NOT NULL,
    CONSTRAINT param_ccf_pk PRIMARY KEY (param_version, product_code),
    CONSTRAINT param_ccf_validity_ck CHECK (valid_from < valid_to),
    CONSTRAINT param_ccf_range_ck CHECK (ccf BETWEEN 0 AND 1),
    CONSTRAINT param_ccf_product_code_fk FOREIGN KEY (product_code) REFERENCES ref_product (product_code)
);

COMMENT ON TABLE param_ccf IS 'Credit conversion factor per product and parameter version (F5).';
COMMENT ON COLUMN param_ccf.param_version IS 'Parameter set version.';
COMMENT ON COLUMN param_ccf.product_code IS 'Product.';
COMMENT ON COLUMN param_ccf.ccf IS 'Credit conversion factor applied to undrawn_amt.';
COMMENT ON COLUMN param_ccf.valid_from IS 'First as_of of validity, inclusive.';
COMMENT ON COLUMN param_ccf.valid_to IS 'End of validity, exclusive; 9999-12-31 when open.';

CREATE TABLE param_haircut (
    param_version NUMBER(4) NOT NULL,
    collateral_type VARCHAR2 (20 CHAR) NOT NULL,
    haircut NUMBER(5, 4) NOT NULL,
    valid_from DATE NOT NULL,
    valid_to DATE NOT NULL,
    CONSTRAINT param_haircut_pk PRIMARY KEY (param_version, collateral_type),
    CONSTRAINT param_haircut_validity_ck CHECK (valid_from < valid_to),
    CONSTRAINT param_haircut_range_ck CHECK (haircut BETWEEN 0 AND 1),
    CONSTRAINT param_haircut_collateral_type_fk FOREIGN KEY (collateral_type)
    REFERENCES ref_collateral_type (collateral_type)
);

COMMENT ON TABLE param_haircut IS 'Supervisory haircut per collateral type and parameter version (F5).';
COMMENT ON COLUMN param_haircut.param_version IS 'Parameter set version.';
COMMENT ON COLUMN param_haircut.collateral_type IS 'Collateral type.';
COMMENT ON COLUMN param_haircut.haircut IS 'Haircut Hc applied to collateral_amt.';
COMMENT ON COLUMN param_haircut.valid_from IS 'First as_of of validity, inclusive.';
COMMENT ON COLUMN param_haircut.valid_to IS 'End of validity, exclusive; 9999-12-31 when open.';

CREATE TABLE param_risk_weight (
    param_version NUMBER(4) NOT NULL,
    exposure_class VARCHAR2 (20 CHAR) NOT NULL,
    rating_bucket VARCHAR2 (20 CHAR) NOT NULL,
    risk_weight NUMBER(6, 4) NOT NULL,
    valid_from DATE NOT NULL,
    valid_to DATE NOT NULL,
    CONSTRAINT param_risk_weight_pk PRIMARY KEY (param_version, exposure_class, rating_bucket),
    CONSTRAINT param_risk_weight_validity_ck CHECK (valid_from < valid_to),
    CONSTRAINT param_risk_weight_range_ck CHECK (risk_weight BETWEEN 0 AND 12.5)
);

COMMENT ON TABLE param_risk_weight IS 'Risk weight per exposure class, rating bucket and parameter version (F5).';
COMMENT ON COLUMN param_risk_weight.param_version IS 'Parameter set version.';
COMMENT ON COLUMN param_risk_weight.exposure_class IS 'Exposure class: a segment code or DEFAULTED.';
COMMENT ON COLUMN param_risk_weight.rating_bucket IS 'Rating bucket.';
COMMENT ON COLUMN param_risk_weight.risk_weight IS 'Risk weight applied to E*.';
COMMENT ON COLUMN param_risk_weight.valid_from IS 'First as_of of validity, inclusive.';
COMMENT ON COLUMN param_risk_weight.valid_to IS 'End of validity, exclusive; 9999-12-31 when open.';

INSERT INTO param_ccf (param_version, product_code, ccf, valid_from, valid_to)
SELECT
    1 AS param_version,
    v.product_code,
    v.ccf,
    DATE '2000-01-01' AS valid_from,
    DATE '9999-12-31' AS valid_to
FROM (VALUES ('LOAN', 0), ('UNDRAWN_LINE', 0.40), ('GUARANTEE', 1.00)) v (product_code, ccf);

INSERT INTO param_haircut (param_version, collateral_type, haircut, valid_from, valid_to)
SELECT
    1 AS param_version,
    v.collateral_type,
    v.haircut,
    DATE '2000-01-01' AS valid_from,
    DATE '9999-12-31' AS valid_to
FROM (VALUES ('CASH', 0), ('SOV_BOND', 0.02), ('CORP_BOND', 0.06), ('EQUITY', 0.20)) v (collateral_type, haircut);

INSERT INTO param_risk_weight (param_version, exposure_class, rating_bucket, risk_weight, valid_from, valid_to)
WITH buckets AS (
    SELECT DISTINCT rating_bucket FROM ref_rating
)

SELECT
    1 AS param_version,
    m.exposure_class,
    b.rating_bucket,
    CASE b.rating_bucket
        WHEN 'AAA_AA' THEN m.aaa_aa
        WHEN 'A' THEN m.a
        WHEN 'BBB' THEN m.bbb
        WHEN 'BB' THEN m.bb
        WHEN 'B' THEN m.b
        WHEN 'CCC_C' THEN m.ccc_c
        WHEN 'NR' THEN m.nr
    END AS risk_weight,
    DATE '2000-01-01' AS valid_from,
    DATE '9999-12-31' AS valid_to
FROM (
    VALUES
    ('SOVEREIGN', 0, 0.20, 0.50, 1.00, 1.00, 1.50, 1.00),
    ('BANK', 0.20, 0.30, 0.50, 1.00, 1.00, 1.50, 1.00),
    ('CORPORATE', 0.20, 0.50, 0.75, 1.00, 1.50, 1.50, 1.00),
    ('SME', 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85),
    ('RETAIL', 0.75, 0.75, 0.75, 0.75, 0.75, 0.75, 0.75),
    ('DEFAULTED', 1.50, 1.50, 1.50, 1.50, 1.50, 1.50, 1.50)
) m (exposure_class, aaa_aa, a, bbb, bb, b, ccc_c, nr)
CROSS JOIN buckets b;
COMMIT;
