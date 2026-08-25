ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE ut_ops AUTHID DEFINER AS
    --%suite(pkg_ops)

    --%test(a LOADED entry with the same feed, as_of_date and sha256 marks the file as loaded)
    PROCEDURE skip_loaded_same_sha256;

    --%test(a FAILED or STARTED entry never marks the file as loaded)
    PROCEDURE failed_load_not_loaded;

    --%test(gold to build starts at the earliest as_of whose gold loads are empty, stale or forced by rebuild-from)
    PROCEDURE dirty_asof_detection;

    --%test(statistics are refused for a table outside the silver and gold list)
    --%throws(-20104)
    PROCEDURE gather_stats_rejects_unknown_table;
END ut_ops;
/
