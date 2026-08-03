#!/bin/bash
set -euo pipefail

if [[ ! "${SRDWH_ENV:?20_dev_ci: SRDWH_ENV is required}" =~ ^(dev|ci)$ ]]; then
  echo "20_dev_ci: skipped (SRDWH_ENV=${SRDWH_ENV})"
  exit 0
fi

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
