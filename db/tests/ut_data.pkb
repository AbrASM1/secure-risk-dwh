ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY ut_data AS
    PROCEDURE add_counterparty(
        p_as_of IN DATE,
        p_cpty_id IN VARCHAR2,
        p_rating IN VARCHAR2 DEFAULT 'BBB',
        p_name IN VARCHAR2 DEFAULT 'Atlas Foods SA',
        p_default IN VARCHAR2 DEFAULT 'N',
        p_segment IN VARCHAR2 DEFAULT 'SME'
    ) IS
    BEGIN
        INSERT INTO slv_counterparty (
            as_of_date, cpty_id, cpty_name, lei, segment_code, country, rating, default_flag, load_id, src_row
        )
        VALUES (p_as_of, p_cpty_id, p_name, NULL, p_segment, 'FR', p_rating, p_default, 0, 1);
    END add_counterparty;

    PROCEDURE add_exposure(
        p_as_of IN DATE,
        p_exposure_id IN VARCHAR2,
        p_cpty_id IN VARCHAR2,
        p_product IN VARCHAR2 DEFAULT 'LOAN',
        p_drawn IN NUMBER DEFAULT 1000,
        p_undrawn IN NUMBER DEFAULT 0
    ) IS
    BEGIN
        INSERT INTO slv_exposure (
            as_of_date, exposure_id, cpty_id, product_code, drawn_amt, undrawn_amt, collateral_amt,
            collateral_type, currency, load_id, src_row
        )
        VALUES (p_as_of, p_exposure_id, p_cpty_id, p_product, p_drawn, p_undrawn, 0, NULL, 'EUR', 0, 1);
    END add_exposure;

    PROCEDURE build(p_as_of IN DATE) IS
        l_rows NUMBER;
    BEGIN
        pkg_gold.build_as_of(0, p_as_of);
        pkg_rwa.compute(0, p_as_of);
        pkg_gold.finish_as_of(0, p_as_of, l_rows);
    END build;
END ut_data;
/
