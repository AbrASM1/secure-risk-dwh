ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE pkg_silver AUTHID DEFINER AS
    c_reconciliation CONSTANT PLS_INTEGER := -20201;
    c_rejects_missing CONSTANT PLS_INTEGER := -20202;

    PROCEDURE reject_counterparties(p_run_id IN NUMBER, p_load_id IN NUMBER);

    PROCEDURE insert_counterparties(p_run_id IN NUMBER, p_load_id IN NUMBER);
END pkg_silver;
/
