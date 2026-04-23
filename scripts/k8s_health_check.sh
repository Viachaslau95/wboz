#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:-wboz}"
DOMAIN="${2:-}"

kubectl -n "${NAMESPACE}" get pods
kubectl -n "${NAMESPACE}" wait --for=condition=ready pod -l app.kubernetes.io/instance=wboz --timeout=120s

if [[ -n "${DOMAIN}" ]]; then
  curl -fsS "https://${DOMAIN}/liveness" >/dev/null
fi

echo "Kubernetes health check passed"
