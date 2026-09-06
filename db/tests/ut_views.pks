ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE ut_views AS
    --%suite(reporting views)

    --%test(V_RWA_BY_CLASS sums the mart per as_of, class and risk weight across segments)
    PROCEDURE rwa_by_class_matches_mart;

    --%test(V_RWA_TREND keeps the last 12 as_of per segment, density empty when EAD is 0)
    PROCEDURE rwa_trend_density;

    --%test(V_TOP_EXPOSURES keeps 20 rows per as_of, by rwa then exposure_id)
    PROCEDURE top_exposures_ties;
END ut_views;
/
