#!/bin/bash
set -euo pipefail

if [[ ! "${SRDWH_ENV:?20_dev_ci: SRDWH_ENV is required}" =~ ^(dev|ci)$ ]]; then
  echo "20_dev_ci: skipped (SRDWH_ENV=${SRDWH_ENV})"
  exit 0
fi

sqlplus -s -L / as sysdba <<SQL
WHENEVER SQLERROR EXIT FAILURE
WHENEVER OSERROR EXIT FAILURE
SET FEEDBACK OFF
ALTER SESSION SET CONTAINER = FREEPDB1;
INSERT INTO srdwh_sec.sec_user_access (username, profile, segment_code)
SELECT a.username, a.profile, a.segment_code
FROM (
  VALUES
  ('ANALYST_CORP', 'ANALYST', 'CORPORATE'),
  ('ANALYST_RETAIL', 'ANALYST', 'RETAIL'),
  ('RISK_MANAGER', 'RISK_MANAGER', NULL),
  ('AUDITOR', 'AUDITOR', NULL)
) a (username, profile, segment_code);
COMMIT;
GRANT r_analyst TO analyst_corp, analyst_retail, probe_noprofile;
GRANT r_risk_manager TO risk_manager;
GRANT r_auditor TO auditor;
GRANT EXECUTE ON srdwh_sec.pkg_sec_ctx TO srdwh_owner;
EXIT
SQL
echo "20_dev_ci: profiles assigned from SEC_USER_ACCESS, PROBE_NOPROFILE without a row"

ut3_password="U$(head -c 96 /dev/urandom | base64 -w0 | tr -dc 'A-Za-z0-9' | cut -c1-23)"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT
cp -r /opt/srdwh/utplsql/source/. "${work}"
cd "${work}"

sqlplus -s -L / as sysdba <<SQL
WHENEVER SQLERROR EXIT FAILURE
WHENEVER OSERROR EXIT FAILURE
ALTER SESSION SET CONTAINER = FREEPDB1;
@create_utplsql_owner.sql UT3 ${ut3_password} USERS
@install.sql UT3
@create_user_grants.sql UT3 SRDWH_OWNER
@create_user_synonyms.sql UT3 SRDWH_OWNER
ALTER USER ut3 ACCOUNT LOCK;
EXIT
SQL

echo "20_dev_ci: utPLSQL installed in FREEPDB1 for SRDWH_OWNER, UT3 locked (SRDWH_ENV=${SRDWH_ENV})"

"$(dirname "$0")/10_deploy.sh" /opt/srdwh/tests/fixtures
"$(dirname "$0")/10_deploy.sh" /opt/srdwh/tests
sqlplus -s -L / as sysdba <<SQL
WHENEVER SQLERROR EXIT FAILURE
WHENEVER OSERROR EXIT FAILURE
SET FEEDBACK OFF
ALTER SESSION SET CONTAINER = FREEPDB1;
@/opt/srdwh/ddl/99_deploy_check.sql
EXIT
SQL
echo "20_dev_ci: db/tests deployed and checked"
