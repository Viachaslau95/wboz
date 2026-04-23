#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:-wboz}"
RELEASE="${2:-wboz}"
DOMAIN="${3:-}"

helm -n "${NAMESPACE}" status "${RELEASE}" >/dev/null
kubectl -n "${NAMESPACE}" get pods,jobs

if [[ -n "${DOMAIN}" ]]; then
  curl -fsS "https://${DOMAIN}/liveness" | grep -q '"status":"ok"'
fi

echo "Kubernetes smoke check passed"
