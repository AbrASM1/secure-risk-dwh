ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE ut_data AS
    PROCEDURE add_counterparty(
        p_as_of IN DATE,
        p_cpty_id IN VARCHAR2,
        p_rating IN VARCHAR2 DEFAULT 'BBB',
        p_name IN VARCHAR2 DEFAULT 'Atlas Foods SA',
        p_default IN VARCHAR2 DEFAULT 'N',
        p_segment IN VARCHAR2 DEFAULT 'SME'
    );

    PROCEDURE add_exposure(
        p_as_of IN DATE,
        p_exposure_id IN VARCHAR2,
        p_cpty_id IN VARCHAR2,
        p_product IN VARCHAR2 DEFAULT 'LOAN',
        p_drawn IN NUMBER DEFAULT 1000,
        p_undrawn IN NUMBER DEFAULT 0
    );

    PROCEDURE load_golden;

    PROCEDURE build(p_as_of IN DATE);
END ut_data;
/
