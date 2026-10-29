#!/usr/bin/env bash
# faults/bad_config_crashloop/reset.sh
# Restore valid DATABASE_URL in api-config and restart api. Wait for healthy.
set -euo pipefail

NS="${NAMESPACE:-staging}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "[reset:bad_config_crashloop] Restoring valid DATABASE_URL in api-config..."
kubectl patch configmap api-config -n "$NS" \
  --type merge \
  -p '{"data":{"DATABASE_URL":"postgresql://labuser:labpass123@db-service:5432/incidentlab"}}'

echo "[reset:bad_config_crashloop] Restarting api deployment..."
kubectl rollout restart deployment/api -n "$NS"

echo "[reset:bad_config_crashloop] Waiting for api rollout to complete..."
kubectl rollout status deployment/api -n "$NS" --timeout=120s

echo "[reset:bad_config_crashloop] Waiting for all staging deployments to be healthy..."
bash "${REPO_ROOT}/scripts/wait-healthy.sh" "$NS" 180

echo "[reset:bad_config_crashloop] Reset complete."
