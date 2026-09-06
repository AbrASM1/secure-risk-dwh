ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE ut_rwa AS
    --%suite(pkg_rwa calculation chain)

    --%test(each as_of takes the parameter version valid at that date)
    PROCEDURE param_version_selection;

    --%test(golden set G1 to G10: class, EAD, E*, risk weight and RWA exact to the cent)
    PROCEDURE golden_set_exact;

    --%test(golden set total RWA is 2,211,000.00)
    PROCEDURE golden_total;

    --%test(a defaulted counterparty takes class DEFAULTED whatever its segment)
    PROCEDURE defaulted_class;

    --%test(rating CCC falls in bucket CCC_C)
    PROCEDURE ccc_bucket;

    --%test(RWA rounds half a cent away from zero and intermediates stay unrounded)
    PROCEDURE rounding_half_cent;

    --%test(each of the 42 class and bucket cells yields the SPEC risk weight)
    PROCEDURE risk_weight_matrix;

    --%test(per as_of, mart counts and sums of ead, e_star and rwa equal the RWA facts)
    PROCEDURE mart_equals_facts;
END ut_rwa;
/
