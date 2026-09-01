ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE ut_rwa AS
    --%suite(pkg_rwa calculation chain)

    --%test(each as_of takes the parameter version valid at that date)
    PROCEDURE param_version_selection;
END ut_rwa;
/
