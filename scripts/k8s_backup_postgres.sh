#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:-wboz}"
DB_RESOURCE="${2:-statefulset/wboz-wboz-postgres}"
DB_USER="${3:-wboz}"
DB_NAME="${4:-wboz}"
BACKUP_DIR="${5:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "${BACKUP_DIR}"

timestamp="$(date -u +%Y%m%d_%H%M%S)"
backup_file="${BACKUP_DIR}/wboz_${timestamp}.sql.gz"

kubectl -n "${NAMESPACE}" exec -i "${DB_RESOURCE}" -- \
  pg_dump -U "${DB_USER}" -d "${DB_NAME}" | gzip > "${backup_file}"

find "${BACKUP_DIR}" -type f -name "wboz_*.sql.gz" -mtime +"${RETENTION_DAYS}" -delete

echo "Backup created: ${backup_file}"
