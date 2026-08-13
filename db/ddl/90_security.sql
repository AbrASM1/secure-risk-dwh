ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
GRANT INSERT, SELECT ON brz_counterparty TO srdwh_etl;
GRANT INSERT, SELECT ON brz_exposure TO srdwh_etl;
GRANT SELECT ON ops_load_registry TO srdwh_etl;
GRANT EXECUTE ON pkg_ops TO srdwh_etl;
GRANT EXECUTE ON pkg_silver TO srdwh_etl;
