ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE ut_gold AUTHID DEFINER AS
    --%suite(pkg_gold counterparty dimension)

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
END ut_gold;
/
