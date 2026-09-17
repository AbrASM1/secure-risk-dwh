ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE ut_sec AS
    --%suite(VPD predicate)

    --%test(pipeline accounts and risk managers read everything, analysts their segment, others nothing)
    PROCEDURE vpd_predicate_branches;
END ut_sec;
/
