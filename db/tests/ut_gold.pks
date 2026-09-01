ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE ut_gold AUTHID DEFINER AS
    --%suite(pkg_gold dimensions, facts and rewind)

    --%test(a change of segment, rating or default closes the current version and opens one at the as_of)
    PROCEDURE scd2_new_version_on_change;

    --%test(name, LEI and country are overwritten on every version without a new version)
    PROCEDURE scd1_overwrites_all_versions;

    --%test(a counterparty missing from a snapshot keeps its current version)
    PROCEDURE missing_counterparty_keeps_version;

    --%test(no two versions of a counterparty overlap)
    PROCEDURE no_overlapping_versions;

    --%test(every counterparty has exactly one current version)
    PROCEDURE one_current_version;

    --%test(each closed version ends where the next one starts)
    PROCEDURE contiguous_versions;

    --%test(one fact row per exposure and as_of, even when an as_of is built twice)
    PROCEDURE fact_grain_unique;

    --%test(each fact points to the counterparty version valid at its as_of)
    PROCEDURE fact_on_valid_version;

    --%test(per as_of, silver exposures equal exposure fact rows and RWA fact rows)
    PROCEDURE counts_silver_fact_rwa;

    --%test(the segment of a fact equals the segment of its counterparty version)
    PROCEDURE segment_matches_version;

    --%test(rewind from D deletes facts and versions from D and reopens the version covering D)
    PROCEDURE rewind_reopens_versions;
END ut_gold;
/
