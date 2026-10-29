#!/usr/bin/env bash
# faults/oom_kill/reset.sh
# Disable LEAK_MODE AND restore memory limit to 256Mi (the baseline).
# Note: raising the limit alone is an UNACCEPTABLE remediation – we must also fix the leak.
set -euo pipefail

NS="${NAMESPACE:-staging}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "[reset:oom_kill] Disabling LEAK_MODE in api-config..."
kubectl patch configmap api-config -n "$NS" \
  --type merge \
  -p '{"data":{"LEAK_MODE":"off"}}'

echo "[reset:oom_kill] Restoring memory limit to 256Mi..."
kubectl patch deployment api -n "$NS" \
  --type json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"256Mi"}]'

echo "[reset:oom_kill] Annotating deployment with change cause..."
kubectl annotate deployment api -n "$NS" \
  kubernetes.io/change-cause="reset:oom_kill – leak disabled, 256Mi limit restored" \
  --overwrite

echo "[reset:oom_kill] Restarting api to pick up changes..."
kubectl rollout restart deployment/api -n "$NS"

echo "[reset:oom_kill] Waiting for rollout..."
kubectl rollout status deployment/api -n "$NS" --timeout=120s

echo "[reset:oom_kill] Waiting for all staging deployments to be healthy..."
bash "${REPO_ROOT}/scripts/wait-healthy.sh" "$NS" 180

echo "[reset:oom_kill] Reset complete."
