ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE ut_params AS
    --%suite(parameter versions)

    --%test(each version holds every product, collateral type, class and bucket under one validity)
    PROCEDURE version_complete;

    --%test(versions chain from 2000-01-01 to the open end without gap or overlap in each table)
    PROCEDURE no_overlap_full_coverage;
END ut_params;
/
