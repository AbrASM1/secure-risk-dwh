ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;

CREATE OR REPLACE VIEW ut_golden_rwa AS
SELECT
    g.golden_id,
    g.segment_code,
    g.rating,
    g.default_flag,
    g.product_code,
    g.drawn_amt,
    g.undrawn_amt,
    g.collateral_amt,
    g.exposure_class,
    g.ead,
    g.e_star,
    g.risk_weight,
    g.rwa,
    nullif(g.collateral_type, 'none') AS collateral_type,
    DATE '2000-01-31' AS as_of_date
FROM (
    VALUES
    (
        'G1', 'CORPORATE', 'AA', 'N', 'LOAN', 1000000, 0, 'none', 0,
        'CORPORATE', 1000000, 1000000, 0.20, 200000.00
    ),
    (
        'G2', 'CORPORATE', 'BBB', 'N', 'UNDRAWN_LINE', 0, 500000, 'none', 0,
        'CORPORATE', 200000, 200000, 0.75, 150000.00
    ),
    (
        'G3', 'CORPORATE', 'A', 'N', 'LOAN', 1000000, 0, 'CORP_BOND', 600000,
        'CORPORATE', 1000000, 436000, 0.50, 218000.00
    ),
    (
        'G4', 'RETAIL', 'NR', 'N', 'LOAN', 50000, 0, 'CASH', 60000,
        'RETAIL', 50000, 0, 0.75, 0.00
    ),
    (
        'G5', 'SOVEREIGN', 'AA', 'N', 'LOAN', 10000000, 0, 'none', 0,
        'SOVEREIGN', 10000000, 10000000, 0, 0.00
    ),
    (
        'G6', 'BANK', 'A', 'N', 'UNDRAWN_LINE', 200000, 300000, 'none', 0,
        'BANK', 320000, 320000, 0.30, 96000.00
    ),
    (
        'G7', 'SME', 'NR', 'N', 'LOAN', 300000, 0, 'EQUITY', 100000,
        'SME', 300000, 220000, 0.85, 187000.00
    ),
    (
        'G8', 'CORPORATE', 'B', 'Y', 'LOAN', 400000, 0, 'none', 0,
        'DEFAULTED', 400000, 400000, 1.50, 600000.00
    ),
    (
        'G9', 'CORPORATE', 'BB', 'N', 'GUARANTEE', 0, 250000, 'none', 0,
        'CORPORATE', 250000, 250000, 1.00, 250000.00
    ),
    (
        'G10', 'SOVEREIGN', 'BBB', 'N', 'LOAN', 2000000, 0, 'SOV_BOND', 1000000,
        'SOVEREIGN', 2000000, 1020000, 0.50, 510000.00
    )
) g (
    golden_id, segment_code, rating, default_flag, product_code, drawn_amt, undrawn_amt, collateral_type,
    collateral_amt, exposure_class, ead, e_star, risk_weight, rwa
);

COMMENT ON TABLE ut_golden_rwa IS 'Test fixture, dev and ci only: golden RWA set of SPEC §7 with expected results.';
COMMENT ON COLUMN ut_golden_rwa.as_of_date IS 'As-of date of the golden set, outside simulator dates.';
COMMENT ON COLUMN ut_golden_rwa.golden_id IS 'Golden case, used as cpty_id and exposure_id.';
COMMENT ON COLUMN ut_golden_rwa.segment_code IS 'Segment of the counterparty.';
COMMENT ON COLUMN ut_golden_rwa.rating IS 'Rating of the counterparty.';
COMMENT ON COLUMN ut_golden_rwa.default_flag IS 'Default flag of the counterparty.';
COMMENT ON COLUMN ut_golden_rwa.product_code IS 'Product of the exposure.';
COMMENT ON COLUMN ut_golden_rwa.drawn_amt IS 'Drawn amount, EUR.';
COMMENT ON COLUMN ut_golden_rwa.undrawn_amt IS 'Undrawn amount, EUR.';
COMMENT ON COLUMN ut_golden_rwa.collateral_type IS 'Collateral type, empty without collateral.';
COMMENT ON COLUMN ut_golden_rwa.collateral_amt IS 'Collateral amount, EUR.';
COMMENT ON COLUMN ut_golden_rwa.exposure_class IS 'Expected exposure class.';
COMMENT ON COLUMN ut_golden_rwa.ead IS 'Expected EAD.';
COMMENT ON COLUMN ut_golden_rwa.e_star IS 'Expected E*.';
COMMENT ON COLUMN ut_golden_rwa.risk_weight IS 'Expected risk weight.';
COMMENT ON COLUMN ut_golden_rwa.rwa IS 'Expected RWA, to the cent.';
