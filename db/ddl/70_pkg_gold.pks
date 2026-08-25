ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE pkg_gold AUTHID DEFINER AS
    c_open_end CONSTANT DATE := DATE '9999-12-31';
    c_counts CONSTANT PLS_INTEGER := -20301;

    PROCEDURE load_counterparties(p_run_id IN NUMBER, p_as_of_date IN DATE);

    PROCEDURE build_as_of(p_run_id IN NUMBER, p_as_of_date IN DATE, p_rows OUT NUMBER);

    PROCEDURE rewind(p_run_id IN NUMBER, p_from IN DATE);
END pkg_gold;
/
