#!/bin/bash
set -euo pipefail

: "${SRDWH_ENV:?00_accounts: SRDWH_ENV is required}"
logins=(SRDWH_OWNER SRDWH_ETL)
if [[ "${SRDWH_ENV}" =~ ^(dev|ci)$ ]]; then
  logins+=(ANALYST_CORP ANALYST_RETAIL RISK_MANAGER AUDITOR PROBE_NOPROFILE)
fi

for account in "${logins[@]}"; do
  variable="${account}_PASSWORD"
  if [[ ! "${!variable:-}" =~ ^[A-Za-z][A-Za-z0-9]{23}$ ]]; then
    echo "00_accounts: ${variable} must hold 24 characters [A-Za-z0-9], the first a letter" >&2
    exit 1
  fi
done

login() {
  local variable="${1}_PASSWORD"
  cat <<SQL
EXEC :pw := '${!variable}'
BEGIN EXECUTE IMMEDIATE 'CREATE USER ${1} IDENTIFIED BY "' || :pw || '"'; END;
/
GRANT CREATE SESSION TO ${1};
SQL
}

{
  cat <<SQL
WHENEVER SQLERROR EXIT FAILURE
WHENEVER OSERROR EXIT FAILURE
SET FEEDBACK OFF VERIFY OFF
ALTER SESSION SET CONTAINER = FREEPDB1;
VARIABLE pw VARCHAR2(128)
SQL
  for account in "${logins[@]}"; do
    login "${account}"
  done
  cat <<SQL
ALTER USER srdwh_owner DEFAULT TABLESPACE users QUOTA UNLIMITED ON users;
GRANT EXECUTE ON sys.dbms_lock TO srdwh_owner;
CREATE USER srdwh_sec NO AUTHENTICATION DEFAULT TABLESPACE users QUOTA UNLIMITED ON users;
GRANT ADMINISTER DATABASE TRIGGER TO srdwh_sec;
EXIT
SQL
} | sqlplus -s -L / as sysdba

echo "00_accounts: ${logins[*]} and SRDWH_SEC created (SRDWH_ENV=${SRDWH_ENV})"
