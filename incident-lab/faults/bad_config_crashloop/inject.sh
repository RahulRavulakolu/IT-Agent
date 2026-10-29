#!/usr/bin/env bash
# faults/bad_config_crashloop/inject.sh
# Fault: Patch api-config with a malformed DATABASE_URL, then rollout restart.
# The api service validates DATABASE_URL at startup and exits 1 → CrashLoopBackOff.
set -euo pipefail

NS="${NAMESPACE:-staging}"

echo "[inject:bad_config_crashloop] Patching api-config with malformed DATABASE_URL..."
kubectl patch configmap api-config -n "$NS" \
  --type merge \
  -p '{"data":{"DATABASE_URL":"not-a-valid-dsn://broken"}}'

echo "[inject:bad_config_crashloop] Triggering rollout restart on api deployment..."
kubectl rollout restart deployment/api -n "$NS" \
  --field-manager=incident-lab-fault

echo "[inject:bad_config_crashloop] Fault injected. Pods will enter CrashLoopBackOff shortly."
echo "  Watch with: kubectl get pods -n ${NS} -l app=api -w"
