#!/usr/bin/env bash
set -euo pipefail

STACK_PATH="${1:-/opt/wboz}"
BACKUP_DIR="${2:-/opt/wboz/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

cd "${STACK_PATH}"
mkdir -p "${BACKUP_DIR}"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a && source .env && set +a
fi

timestamp="$(date -u +%Y%m%d_%H%M%S)"
backup_file="${BACKUP_DIR}/wboz_${timestamp}.sql.gz"

docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U "${POSTGRES_USER:-wboz}" -d "${POSTGRES_DB:-wboz}" \
  | gzip > "${backup_file}"

find "${BACKUP_DIR}" -type f -name "wboz_*.sql.gz" -mtime +"${RETENTION_DAYS}" -delete

echo "Backup created: ${backup_file}"
