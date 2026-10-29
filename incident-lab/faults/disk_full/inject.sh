#!/usr/bin/env bash
# faults/disk_full/inject.sh
# Fill the api /data tmpfs (64Mi) with junk files via kubectl exec.
# Idempotent: existing dump files are removed first to ensure a clean fill.
set -euo pipefail

NS="${NAMESPACE:-staging}"

# Pick first Running api pod
API_POD=$(kubectl get pods -n "$NS" -l app=api \
  --field-selector=status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}')

if [[ -z "$API_POD" ]]; then
  echo "[inject:disk_full] ERROR: No running api pod found in namespace ${NS}."
  exit 1
fi

echo "[inject:disk_full] Target pod: ${API_POD}"
echo "[inject:disk_full] Removing any previous dump files..."
kubectl exec -n "$NS" "$API_POD" -- \
  sh -c 'rm -f /data/tmp_dump_*.bin 2>/dev/null || true'

echo "[inject:disk_full] Writing junk files to fill /data (64Mi tmpfs)..."
# Write 4 × 16 MB = 64 MB – leaves OS metadata but fills tmpfs very close to full
for i in 1 2 3 4; do
  echo "[inject:disk_full]   Writing tmp_dump_${i}.bin (16 MB)..."
  kubectl exec -n "$NS" "$API_POD" -- \
    dd if=/dev/urandom of="/data/tmp_dump_${i}.bin" bs=1M count=16 2>/dev/null || true
done

echo "[inject:disk_full] Disk fill complete. Current /data usage:"
kubectl exec -n "$NS" "$API_POD" -- df -h /data

echo "[inject:disk_full] Fault injected. POST /items calls will now fail with 507 / ENOSPC."
