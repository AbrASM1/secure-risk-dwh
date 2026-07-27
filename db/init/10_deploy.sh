#!/bin/bash
set -euo pipefail

ddl=/opt/srdwh/ddl
opening='^ALTER SESSION SET CURRENT_SCHEMA = (srdwh_owner|srdwh_sec);$'

run() {
  if [[ ! "$(head -n 1 "$1")" =~ ${opening} ]]; then
    echo "10_deploy: $(basename "$1") must open with ALTER SESSION SET CURRENT_SCHEMA" >&2
    exit 1
  fi
  sqlplus -s -L / as sysdba <<SQL
WHENEVER SQLERROR EXIT FAILURE
WHENEVER OSERROR EXIT FAILURE
SET FEEDBACK OFF
ALTER SESSION SET CONTAINER = FREEPDB1;
@$1
EXIT
SQL
  echo "10_deploy: $(basename "$1")"
}

mapfile -t stems < <(find "${ddl}" -maxdepth 1 -type f \( -name '*.sql' -o -name '*.pks' -o -name '*.pkb' \) \
  | sed 's/\.[^.]*$//' | LC_ALL=C sort -u)
for stem in "${stems[@]}"; do
  for extension in sql pks pkb; do
    if [[ -f "${stem}.${extension}" ]]; then
      run "${stem}.${extension}"
    fi
  done
done
