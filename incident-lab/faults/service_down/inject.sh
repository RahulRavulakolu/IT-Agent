#!/usr/bin/env bash
# faults/service_down/inject.sh
# Scale web deployment to 0 replicas.
set -euo pipefail

NS="${NAMESPACE:-staging}"

echo "[inject:service_down] Scaling web deployment to 0 replicas..."
kubectl scale deployment/web -n "$NS" --replicas=0

echo "[inject:service_down] Fault injected."
echo "  Web is now unavailable. Traffic generator will log errors."
echo "  Watch with: kubectl get pods -n ${NS} -l app=web -w"
