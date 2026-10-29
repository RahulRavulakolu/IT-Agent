#!/usr/bin/env bash
# faults/disk_full/reset.sh
# Remove junk dump files from /data in all api pods to free up tmpfs space.
# Optionally also rotate archive files (acceptable remediation path).
set -euo pipefail

NS="${NAMESPACE:-staging}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "[reset:disk_full] Removing junk dump files from all api pods..."
for POD in $(kubectl get pods -n "$NS" -l app=api \
  --field-selector=status.phase=Running \
  -o jsonpath='{.items[*].metadata.name}'); do
  echo "[reset:disk_full]   Cleaning pod: ${POD}"
  kubectl exec -n "$NS" "$POD" -- \
    sh -c 'rm -f /data/tmp_dump_*.bin 2>/dev/null; echo "  df: $(df -h /data | tail -1)"'
done

echo "[reset:disk_full] Waiting for app_data_volume_used_ratio to drop..."
sleep 10  # Give Prometheus a scrape cycle

echo "[reset:disk_full] Checking all staging deployments healthy..."
bash "${REPO_ROOT}/scripts/wait-healthy.sh" "$NS" 120

echo "[reset:disk_full] Reset complete."
