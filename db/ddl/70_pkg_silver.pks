ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE pkg_silver AUTHID DEFINER AS
    c_reconciliation CONSTANT PLS_INTEGER := -20201;
    c_rejects_missing CONSTANT PLS_INTEGER := -20202;
    c_as_of_mismatch CONSTANT PLS_INTEGER := -20203;

    PROCEDURE reject_counterparties(p_run_id IN NUMBER, p_load_id IN NUMBER);

    PROCEDURE reject_exposures(p_run_id IN NUMBER, p_load_id IN NUMBER, p_cpty_load_id IN NUMBER);

    PROCEDURE replace_as_of(p_run_id IN NUMBER, p_cpty_load_id IN NUMBER, p_expo_load_id IN NUMBER);
END pkg_silver;
/
