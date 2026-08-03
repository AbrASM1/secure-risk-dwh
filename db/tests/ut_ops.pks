ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE ut_ops AUTHID DEFINER AS
    --%suite(pkg_ops)

    --%test(a LOADED entry with the same feed, as_of_date and sha256 marks the file as loaded)
    PROCEDURE skip_loaded_same_sha256;

    --%test(a FAILED or STARTED entry never marks the file as loaded)
    PROCEDURE failed_load_not_loaded;
END ut_ops;
/
