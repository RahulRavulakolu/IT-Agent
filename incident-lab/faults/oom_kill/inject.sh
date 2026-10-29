#!/usr/bin/env bash
# faults/oom_kill/inject.sh
# Enable LEAK_MODE=on in api-config AND lower memory limit to 64Mi.
# The pod will grow memory until OOMKilled (exit code 137).
set -euo pipefail

NS="${NAMESPACE:-staging}"

echo "[inject:oom_kill] Enabling LEAK_MODE=on in api-config..."
kubectl patch configmap api-config -n "$NS" \
  --type merge \
  -p '{"data":{"LEAK_MODE":"on"}}'

echo "[inject:oom_kill] Lowering api memory limit to 64Mi..."
kubectl patch deployment api -n "$NS" \
  --type json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"64Mi"}]'

echo "[inject:oom_kill] Annotating deployment with change cause..."
kubectl annotate deployment api -n "$NS" \
  kubernetes.io/change-cause="fault:oom_kill – leak+64Mi limit" \
  --overwrite

echo "[inject:oom_kill] Restarting api to pick up config changes..."
kubectl rollout restart deployment/api -n "$NS"

echo "[inject:oom_kill] Fault injected. Watch memory grow and OOMKill occur:"
echo "  kubectl top pods -n ${NS} -l app=api"
echo "  kubectl get pods -n ${NS} -l app=api -w"
