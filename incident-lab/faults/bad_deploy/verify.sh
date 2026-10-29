#!/usr/bin/env bash
# faults/bad_deploy/verify.sh
# Verify bad_deploy symptoms: high 5xx rate, elevated p95 latency, 2+ rollout revisions.
set -euo pipefail

NS="${NAMESPACE:-staging}"
PROM_URL="${PROM_URL:-http://127.0.0.1:9090}"
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

echo "[verify:bad_deploy] Polling for symptoms (timeout: ${TIMEOUT}s)..."
echo "  Note: waiting for load generator to accumulate traffic on v2-bad..."

SYMPTOM_5XX=false
SYMPTOM_LATENCY=false
SYMPTOM_REVISIONS=false

start=$(date +%s)
while true; do
  now=$(date +%s)
  elapsed=$((now - start))
  if [[ $elapsed -ge $TIMEOUT ]]; then
    echo ""
    fail "TIMEOUT after ${TIMEOUT}s."
    [[ $SYMPTOM_5XX       == true ]] && pass "5xx rate > 50%"          || fail "5xx rate NOT > 50%"
    [[ $SYMPTOM_LATENCY   == true ]] && pass "p95 latency > 1s"        || fail "p95 latency NOT > 1s"
    [[ $SYMPTOM_REVISIONS == true ]] && pass ">= 2 rollout revisions"  || fail "< 2 rollout revisions"
    exit 1
  fi

  # Symptom 1: 5xx rate fraction > 0.5 (50%)
  total_rate=$(check_prom 'sum(rate(http_requests_total{service="api"}[2m]))')
  error_rate=$(check_prom 'sum(rate(http_requests_total{service="api",status=~"5.."}[2m]))')
  if [[ -n "$total_rate" && -n "$error_rate" ]]; then
    ok=$(echo "$total_rate > 0 && $error_rate / $total_rate > 0.5" | bc -l 2>/dev/null || echo 0)
    [[ "$ok" == "1" ]] && SYMPTOM_5XX=true
  fi

  # Symptom 2: p95 latency > 1s
  p95=$(check_prom 'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service="api"}[2m])) by (le))')
  if [[ -n "$p95" ]]; then
    ok=$(echo "$p95 > 1.0" | bc -l 2>/dev/null || echo 0)
    [[ "$ok" == "1" ]] && SYMPTOM_LATENCY=true
  fi

  # Symptom 3: deployment has >= 2 revisions
  rev_count=$(kubectl rollout history deployment/api -n "$NS" 2>/dev/null | grep -c "^[0-9]" || echo "0")
  [[ "$rev_count" -ge 2 ]] && SYMPTOM_REVISIONS=true

  if [[ $SYMPTOM_5XX == true && $SYMPTOM_LATENCY == true && $SYMPTOM_REVISIONS == true ]]; then
    echo ""
    pass "All bad_deploy symptoms verified in ${elapsed}s."
    pass "  5xx error rate > 50%"
    pass "  p95 latency > 1s (actual: ${p95:-N/A}s)"
    pass "  >= 2 rollout revisions"
    exit 0
  fi

  info "Elapsed ${elapsed}s – 5xx=${SYMPTOM_5XX} latency=${SYMPTOM_LATENCY}(${p95:-N/A}s) revisions=${SYMPTOM_REVISIONS}(${rev_count})"
  sleep $INTERVAL
done
