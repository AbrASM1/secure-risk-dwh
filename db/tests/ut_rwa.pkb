ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY ut_rwa AS
    c_jan CONSTANT DATE := DATE '2001-01-31';
    c_feb CONSTANT DATE := DATE '2001-02-28';
    c_v2_from CONSTANT DATE := DATE '2001-02-01';

    PROCEDURE add_version_2 IS
    BEGIN
        INSERT INTO param_ccf (param_version, product_code, ccf, valid_from, valid_to)
        SELECT
            2 AS param_version,
            product_code,
            CASE product_code WHEN 'UNDRAWN_LINE' THEN 0.5 ELSE ccf END AS ccf,
            c_v2_from AS valid_from,
            valid_to
        FROM param_ccf
        WHERE param_version = 1;
        INSERT INTO param_haircut (param_version, collateral_type, haircut, valid_from, valid_to)
        SELECT
            2 AS param_version,
            collateral_type,
            haircut,
            c_v2_from AS valid_from,
            valid_to
        FROM param_haircut
        WHERE param_version = 1;
        INSERT INTO param_risk_weight (param_version, exposure_class, rating_bucket, risk_weight, valid_from, valid_to)
        SELECT
            2 AS param_version,
            exposure_class,
            rating_bucket,
            risk_weight,
            c_v2_from AS valid_from,
            valid_to
        FROM param_risk_weight
        WHERE param_version = 1;
        UPDATE param_ccf SET valid_to = c_v2_from WHERE param_version = 1;
        UPDATE param_haircut SET valid_to = c_v2_from WHERE param_version = 1;
        UPDATE param_risk_weight SET valid_to = c_v2_from WHERE param_version = 1;
    END add_version_2;

    PROCEDURE param_version_selection IS
        l_jan gld_fact_rwa%ROWTYPE;
        l_feb gld_fact_rwa%ROWTYPE;
    BEGIN
        add_version_2;
        ut_data.add_counterparty(c_jan, 'UTR1', p_segment => 'CORPORATE');
        ut_data.add_exposure(c_jan, 'UTRE1', 'UTR1', p_product => 'UNDRAWN_LINE', p_drawn => 0, p_undrawn => 1000);
        ut_data.build(c_jan);
        ut_data.add_counterparty(c_feb, 'UTR1', p_segment => 'CORPORATE');
        ut_data.add_exposure(c_feb, 'UTRE1', 'UTR1', p_product => 'UNDRAWN_LINE', p_drawn => 0, p_undrawn => 1000);
        ut_data.build(c_feb);
        SELECT * INTO l_jan
        FROM gld_fact_rwa
        WHERE as_of_date = c_jan AND exposure_id = 'UTRE1';
        SELECT * INTO l_feb
        FROM gld_fact_rwa
        WHERE as_of_date = c_feb AND exposure_id = 'UTRE1';
        ut.expect(l_jan.param_version).to_equal(1);
        ut.expect(l_jan.ccf).to_equal(0.4);
        ut.expect(l_jan.ead).to_equal(400);
        ut.expect(l_jan.rwa).to_equal(300);
        ut.expect(l_feb.param_version).to_equal(2);
        ut.expect(l_feb.ccf).to_equal(0.5);
        ut.expect(l_feb.ead).to_equal(500);
        ut.expect(l_feb.rwa).to_equal(375);
    END param_version_selection;
END ut_rwa;
/
