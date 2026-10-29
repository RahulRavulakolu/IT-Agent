#!/usr/bin/env bash
# faults/bad_deploy/reset.sh
# Roll back api to previous revision (api:v1) using kubectl rollout undo.
# NOTE: simply restarting pods would NOT fix this – the bad image would restart too.
set -euo pipefail

NS="${NAMESPACE:-staging}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "[reset:bad_deploy] Rolling back api deployment to previous revision..."
kubectl rollout undo deployment/api -n "$NS"

echo "[reset:bad_deploy] Annotating with change cause..."
kubectl annotate deployment api -n "$NS" \
  kubernetes.io/change-cause="reset:bad_deploy – rollback to v1" \
  --overwrite

echo "[reset:bad_deploy] Waiting for rollout to complete..."
kubectl rollout status deployment/api -n "$NS" --timeout=120s

echo "[reset:bad_deploy] Verifying api image is back to v1..."
current_image=$(kubectl get deployment api -n "$NS" \
  -o jsonpath='{.spec.template.spec.containers[0].image}')
echo "[reset:bad_deploy] Current image: ${current_image}"

if [[ "$current_image" != "api:v1" ]]; then
  echo "[reset:bad_deploy] WARNING: image is '${current_image}', expected 'api:v1'. Manual check needed."
fi

echo "[reset:bad_deploy] Waiting for all staging deployments to be healthy..."
bash "${REPO_ROOT}/scripts/wait-healthy.sh" "$NS" 180

echo "[reset:bad_deploy] Reset complete."
