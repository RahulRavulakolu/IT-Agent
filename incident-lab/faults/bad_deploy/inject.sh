#!/usr/bin/env bash
# faults/bad_deploy/inject.sh
# Switch api image to v2-bad. Rollout completes (pods pass readiness) but
# then returns ~70% HTTP 500 with ~1.5s extra latency on non-health paths.
set -euo pipefail

NS="${NAMESPACE:-staging}"

echo "[inject:bad_deploy] Setting api image to api:v2-bad..."
kubectl set image deployment/api api=api:v2-bad -n "$NS"

echo "[inject:bad_deploy] Annotating with change cause..."
kubectl annotate deployment api -n "$NS" \
  kubernetes.io/change-cause="fault:bad_deploy – image api:v2-bad" \
  --overwrite

echo "[inject:bad_deploy] Waiting for rollout to complete (pods will pass readiness)..."
kubectl rollout status deployment/api -n "$NS" --timeout=120s

echo "[inject:bad_deploy] Fault injected. Rollout is DONE and pods are Ready."
echo "  But ~70% of API requests will now return HTTP 500 with +1.5s latency."
echo "  Rollout history: kubectl rollout history deployment/api -n ${NS}"
