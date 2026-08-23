ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE pkg_gold AUTHID DEFINER AS
    c_open_end CONSTANT DATE := DATE '9999-12-31';

    PROCEDURE load_counterparties(p_run_id IN NUMBER, p_as_of_date IN DATE);
END pkg_gold;
/
