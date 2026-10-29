#!/usr/bin/env bash
# wait-healthy.sh – Wait until all deployments in a namespace have their desired replicas ready.
# Usage: wait-healthy.sh <namespace> [timeout_seconds]
set -euo pipefail

NAMESPACE=${1:-staging}
TIMEOUT=${2:-300}
INTERVAL=5

echo "[wait-healthy] Waiting for all deployments in '${NAMESPACE}' to be ready (timeout: ${TIMEOUT}s)..."

start=$(date +%s)
while true; do
  now=$(date +%s)
  elapsed=$((now - start))
  if [[ $elapsed -ge $TIMEOUT ]]; then
    echo "[wait-healthy] TIMEOUT after ${TIMEOUT}s. Current state:"
    kubectl get pods -n "$NAMESPACE" -o wide
    echo ""
    kubectl get deployments -n "$NAMESPACE"
    exit 1
  fi

  # Count deployments that are not yet fully ready
  not_ready=$(kubectl get deployments -n "$NAMESPACE" \
    -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.readyReplicas}{" "}{.spec.replicas}{"\n"}{end}' 2>/dev/null \
    | awk '$2 != $3 || $3 == "" {print $1}' | wc -l | tr -d ' ')

  if [[ "$not_ready" -eq 0 ]]; then
    echo "[wait-healthy] All deployments in '${NAMESPACE}' are ready."
    break
  fi

  echo "[wait-healthy] ${not_ready} deployment(s) not yet ready (${elapsed}s elapsed)..."
  sleep $INTERVAL
done
