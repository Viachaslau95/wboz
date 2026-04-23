#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <backup.sql.gz> [namespace] [db-resource] [db-user] [db-name]"
  exit 1
fi

BACKUP_FILE="$1"
NAMESPACE="${2:-wboz}"
DB_RESOURCE="${3:-statefulset/wboz-wboz-postgres}"
DB_USER="${4:-wboz}"
DB_NAME="${5:-wboz}"

if [[ ! -f "${BACKUP_FILE}" ]]; then
  echo "Backup file not found: ${BACKUP_FILE}"
  exit 1
fi

gunzip -c "${BACKUP_FILE}" | kubectl -n "${NAMESPACE}" exec -i "${DB_RESOURCE}" -- \
  psql -U "${DB_USER}" -d "${DB_NAME}"

echo "Restore complete from ${BACKUP_FILE}"
