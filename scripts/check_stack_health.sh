#!/usr/bin/env bash
set -euo pipefail

STACK_PATH="${1:-/opt/wboz}"

cd "${STACK_PATH}"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a && source .env && set +a
fi

docker compose -f docker-compose.prod.yml ps
curl -fsS "https://${DOMAIN}/liveness" >/dev/null

echo "Health check passed"
