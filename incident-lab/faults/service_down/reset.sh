#!/usr/bin/env bash
# faults/service_down/reset.sh
# Scale web back to 2 replicas and wait for it to be healthy.
set -euo pipefail

NS="${NAMESPACE:-staging}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "[reset:service_down] Scaling web deployment back to 2 replicas..."
kubectl scale deployment/web -n "$NS" --replicas=2

echo "[reset:service_down] Waiting for rollout..."
kubectl rollout status deployment/web -n "$NS" --timeout=120s

echo "[reset:service_down] Waiting for all staging deployments to be healthy..."
bash "${REPO_ROOT}/scripts/wait-healthy.sh" "$NS" 120

echo "[reset:service_down] Reset complete."
