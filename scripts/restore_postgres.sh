#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <backup-file.sql.gz> [stack-path]"
  exit 1
fi

BACKUP_FILE="$1"
STACK_PATH="${2:-/opt/wboz}"

if [[ ! -f "${BACKUP_FILE}" ]]; then
  echo "Backup file not found: ${BACKUP_FILE}"
  exit 1
fi

cd "${STACK_PATH}"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a && source .env && set +a
fi

gunzip -c "${BACKUP_FILE}" | docker compose -f docker-compose.prod.yml exec -T db \
  psql -U "${POSTGRES_USER:-wboz}" -d "${POSTGRES_DB:-wboz}"

echo "Restore complete from ${BACKUP_FILE}"
