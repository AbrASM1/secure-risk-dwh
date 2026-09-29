ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE BODY ut_sec AS
    c_segment CONSTANT VARCHAR2(100) := 'segment_code = sys_context(''SRDWH_CTX'', ''SEGMENT'')';

    FUNCTION predicate(p_user IN VARCHAR2, p_profile IN VARCHAR2, p_object IN VARCHAR2) RETURN VARCHAR2 IS
    BEGIN
        RETURN srdwh_sec.pkg_sec_ctx.predicate(p_user, p_profile, p_object);
    END predicate;

    PROCEDURE vpd_predicate_branches IS
    BEGIN
        ut.expect(predicate('SRDWH_OWNER', NULL, 'GLD_FACT_RWA')).to_be_null();
        ut.expect(predicate('SRDWH_ETL', NULL, 'GLD_DIM_COUNTERPARTY')).to_be_null();
        ut.expect(predicate('RISK_MANAGER', 'RISK_MANAGER', 'GLD_FACT_EXPOSURE')).to_be_null();
        ut.expect(predicate('AUDITOR', 'AUDITOR', 'GLD_MART_RWA')).to_be_null();
        ut.expect(predicate('AUDITOR', 'AUDITOR', 'GLD_FACT_RWA')).to_equal('1=0');
        ut.expect(predicate('ANALYST_CORP', 'ANALYST', 'GLD_MART_RWA')).to_equal(c_segment);
        ut.expect(predicate('ANALYST_CORP', 'ANALYST', 'GLD_DIM_COUNTERPARTY')).to_equal(c_segment);
        ut.expect(predicate('PROBE_NOPROFILE', NULL, 'GLD_FACT_RWA')).to_equal('1=0');
        ut.expect(predicate('PROBE_NOPROFILE', NULL, 'GLD_MART_RWA')).to_equal('1=0');
        ut.expect(predicate(NULL, 'UNKNOWN', 'GLD_FACT_RWA')).to_equal('1=0');
    END vpd_predicate_branches;

    PROCEDURE logon_context_failure_denies IS
        l_profile VARCHAR2(30);
    BEGIN
        srdwh_sec.pkg_sec_ctx.set_profile;
        l_profile := sys_context('SRDWH_CTX', 'PROFILE');
        ut.expect(l_profile).to_be_null();
        ut.expect(predicate('ANALYST_CORP', l_profile, 'GLD_FACT_EXPOSURE')).to_equal('1=0');
        ut.expect(predicate('ANALYST_CORP', l_profile, 'GLD_MART_RWA')).to_equal('1=0');
    END logon_context_failure_denies;
END ut_sec;
/
