#!/usr/bin/env bash
# faults/disk_full/verify.sh
# Verify disk_full symptoms via Prometheus and Loki APIs.
set -euo pipefail

NS="${NAMESPACE:-staging}"
PROM_URL="${PROM_URL:-http://127.0.0.1:9090}"
LOKI_URL="${LOKI_URL:-http://127.0.0.1:3100}"
TIMEOUT=${TIMEOUT_SECONDS:-180}
INTERVAL=10

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
pass() { echo -e "${GREEN}[PASS]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
info() { echo -e "${YELLOW}[wait]${NC} $*"; }

check_prom() {
  curl -sf "${PROM_URL}/api/v1/query" \
    --data-urlencode "query=${1}" 2>/dev/null \
    | jq -r '.data.result[0].value[1] // empty' 2>/dev/null || echo ""
}

check_loki() {
  local start_ns
  start_ns=$(python3 -c "import time; print(int((time.time()-300)*1e9))" 2>/dev/null || echo "0")
  curl -sf "${LOKI_URL}/loki/api/v1/query_range" \
    --data-urlencode "query=${1}" \
    --data-urlencode "start=${start_ns}" \
    --data-urlencode "limit=5" 2>/dev/null \
    | jq -r '.data.result | length' 2>/dev/null || echo "0"
}

echo "[verify:disk_full] Polling for symptoms (timeout: ${TIMEOUT}s)..."

SYMPTOM_RATIO=false
SYMPTOM_LOG=false
SYMPTOM_5XX=false

start=$(date +%s)
while true; do
  now=$(date +%s)
  elapsed=$((now - start))
  if [[ $elapsed -ge $TIMEOUT ]]; then
    echo ""
    fail "TIMEOUT after ${TIMEOUT}s."
    [[ $SYMPTOM_RATIO == true ]] && pass "volume ratio >= 0.9"   || fail "volume ratio NOT >= 0.9"
    [[ $SYMPTOM_5XX   == true ]] && pass "5xx rate elevated"      || fail "5xx rate NOT elevated"
    [[ $SYMPTOM_LOG   == true ]] && pass "ENOSPC log found"       || fail "ENOSPC log NOT found"
    exit 1
  fi

  # Symptom 1: app_data_volume_used_ratio >= 0.9 on any api instance
  ratio_val=$(check_prom 'max(app_data_volume_used_ratio{service="api"})')
  if [[ -n "$ratio_val" ]]; then
    ok=$(echo "$ratio_val >= 0.9" | bc -l 2>/dev/null || echo 0)
    [[ "$ok" == "1" ]] && SYMPTOM_RATIO=true
  fi

  # Symptom 2: 5xx rate > 0 on api
  rate_val=$(check_prom 'sum(rate(http_requests_total{service="api",status=~"5.."}[1m]))')
  if [[ -n "$rate_val" ]]; then
    ok=$(echo "$rate_val > 0" | bc -l 2>/dev/null || echo 0)
    [[ "$ok" == "1" ]] && SYMPTOM_5XX=true
  fi

  # Symptom 3: ENOSPC log in Loki
  log_count=$(check_loki '{namespace="staging",app="api"} |= "No space left on device"')
  [[ "$log_count" -gt 0 ]] && SYMPTOM_LOG=true

  if [[ $SYMPTOM_RATIO == true && $SYMPTOM_5XX == true && $SYMPTOM_LOG == true ]]; then
    echo ""
    pass "All disk_full symptoms verified in ${elapsed}s."
    pass "  app_data_volume_used_ratio >= 0.9"
    pass "  5xx rate elevated on api"
    pass "  ENOSPC error in Loki logs"
    exit 0
  fi

  info "Elapsed ${elapsed}s – ratio=${SYMPTOM_RATIO} 5xx=${SYMPTOM_5XX} log=${SYMPTOM_LOG} (ratio_val=${ratio_val:-N/A})"
  sleep $INTERVAL
done
