ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
GRANT INSERT, SELECT ON brz_counterparty TO srdwh_etl;
GRANT INSERT, SELECT ON brz_exposure TO srdwh_etl;
GRANT SELECT ON ops_load_registry TO srdwh_etl;
GRANT EXECUTE ON pkg_ops TO srdwh_etl;
GRANT EXECUTE ON pkg_silver TO srdwh_etl;
GRANT EXECUTE ON pkg_gold TO srdwh_etl;
GRANT EXECUTE ON pkg_rwa TO srdwh_etl;
GRANT SELECT ON v_rwa_by_class TO srdwh_etl;
GRANT SELECT ON v_rwa_trend TO srdwh_etl;
GRANT SELECT ON v_top_exposures TO srdwh_etl;
GRANT REFERENCES ON ref_segment TO srdwh_sec;
GRANT EXECUTE ON pkg_err TO srdwh_sec;

CREATE ROLE r_analyst;
CREATE ROLE r_risk_manager;
CREATE ROLE r_auditor;

GRANT SELECT ON gld_dim_date TO r_analyst, r_risk_manager;
GRANT SELECT ON gld_dim_product TO r_analyst, r_risk_manager;
GRANT SELECT ON gld_dim_counterparty TO r_analyst, r_risk_manager;
GRANT SELECT ON gld_fact_exposure TO r_analyst, r_risk_manager;
GRANT SELECT ON gld_fact_rwa TO r_analyst, r_risk_manager;
GRANT SELECT ON gld_mart_rwa TO r_analyst, r_risk_manager, r_auditor;
GRANT SELECT ON v_rwa_by_class TO r_analyst, r_risk_manager, r_auditor;
GRANT SELECT ON v_rwa_trend TO r_analyst, r_risk_manager, r_auditor;
GRANT SELECT ON v_top_exposures TO r_analyst, r_risk_manager;
GRANT audit_viewer TO r_auditor;

ALTER SESSION SET CURRENT_SCHEMA = srdwh_sec;

CREATE TABLE sec_user_access (
    username VARCHAR2(128) NOT NULL,
    profile VARCHAR2(20) NOT NULL,
    segment_code VARCHAR2 (20 CHAR),
    CONSTRAINT sec_user_access_pk PRIMARY KEY (username),
    CONSTRAINT sec_user_access_profile_ck CHECK (profile IN ('ANALYST', 'RISK_MANAGER', 'AUDITOR')),
    CONSTRAINT sec_user_access_segment_ck CHECK (
        (profile = 'ANALYST' AND segment_code IS NOT NULL) OR (profile <> 'ANALYST' AND segment_code IS NULL)
    ),
    CONSTRAINT sec_user_access_segment_code_fk FOREIGN KEY (segment_code)
    REFERENCES srdwh_owner.ref_segment (segment_code)
);

COMMENT ON TABLE sec_user_access IS 'Access profile of each named account; segment set only for analysts (F7).';
COMMENT ON COLUMN sec_user_access.username IS 'Oracle account name.';
COMMENT ON COLUMN sec_user_access.profile IS 'ANALYST, RISK_MANAGER or AUDITOR.';
COMMENT ON COLUMN sec_user_access.segment_code IS 'Segment of an analyst, empty otherwise.';

CREATE OR REPLACE PACKAGE pkg_sec_ctx AUTHID DEFINER AS
    procedure SET_PROFILE;

    FUNCTION predicate(p_session_user IN VARCHAR2, p_profile IN VARCHAR2, p_object IN VARCHAR2) RETURN VARCHAR2;
END pkg_sec_ctx;
/

CREATE OR REPLACE PACKAGE BODY pkg_sec_ctx AS
    PROCEDURE set_profile IS -- F7
        l_profile sec_user_access.profile%TYPE;
        l_segment sec_user_access.segment_code%TYPE;
    BEGIN
        SELECT
            max(profile) AS profile,
            max(segment_code) AS segment_code
        INTO l_profile, l_segment
        FROM sec_user_access
        WHERE username = sys_context('USERENV', 'SESSION_USER');
        IF l_profile IS NOT NULL THEN
            dbms_session.set_context('SRDWH_CTX', 'PROFILE', l_profile);
            dbms_session.set_context('SRDWH_CTX', 'SEGMENT', l_segment);
        END IF;
    END set_profile;

    FUNCTION predicate(p_session_user IN VARCHAR2, p_profile IN VARCHAR2, p_object IN VARCHAR2) RETURN VARCHAR2 IS -- F7
    BEGIN
        RETURN CASE
            WHEN p_session_user IN ('SRDWH_OWNER', 'SRDWH_ETL') THEN NULL
            WHEN p_profile = 'RISK_MANAGER' THEN NULL
            WHEN p_profile = 'AUDITOR' AND p_object = 'GLD_MART_RWA' THEN NULL
            WHEN p_profile = 'ANALYST' THEN 'segment_code = sys_context(''SRDWH_CTX'', ''SEGMENT'')'
            ELSE '1=0'
        END;
    END predicate;
END pkg_sec_ctx;
/

CREATE OR REPLACE FUNCTION sec_vpd_predicate(p_schema IN VARCHAR2, p_object IN VARCHAR2)
RETURN VARCHAR2 AUTHID DEFINER IS
BEGIN
    RETURN pkg_sec_ctx.predicate(sys_context('USERENV', 'SESSION_USER'), sys_context('SRDWH_CTX', 'PROFILE'), p_object);
END sec_vpd_predicate;
/

CREATE CONTEXT srdwh_ctx USING srdwh_sec.pkg_sec_ctx;

CREATE OR REPLACE TRIGGER sec_logon_trg AFTER LOGON ON DATABASE
BEGIN
    pkg_sec_ctx.set_profile;
EXCEPTION
    WHEN OTHERS THEN
        BEGIN
            srdwh_owner.pkg_err.log_error(NULL, 'logon');
        EXCEPTION
            WHEN OTHERS THEN
                NULL;
        END;
END;
/

DECLARE
    PROCEDURE protect(p_table IN VARCHAR2) IS
    BEGIN
        dbms_rls.add_policy(
            object_schema => 'SRDWH_OWNER',
            object_name => p_table,
            policy_name => 'VPD_SEGMENT',
            function_schema => 'SRDWH_SEC',
            policy_function => 'SEC_VPD_PREDICATE',
            policy_type => dbms_rls.context_sensitive
        );
    END protect;
BEGIN
    protect('GLD_FACT_EXPOSURE');
    protect('GLD_FACT_RWA');
    protect('GLD_DIM_COUNTERPARTY');
    protect('GLD_MART_RWA');
END;
/
