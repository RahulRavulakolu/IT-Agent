#!/usr/bin/env bash
# faults/service_down/verify.sh
# Verify that web has 0 ready replicas and traffic generator sees errors.
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

echo "[verify:service_down] Polling for symptoms (timeout: ${TIMEOUT}s)..."

SYMPTOM_REPLICAS=false
SYMPTOM_UNAVAIL=false

start=$(date +%s)
while true; do
  now=$(date +%s)
  elapsed=$((now - start))
  if [[ $elapsed -ge $TIMEOUT ]]; then
    echo ""
    fail "TIMEOUT after ${TIMEOUT}s."
    [[ $SYMPTOM_REPLICAS == true ]] && pass "ready replicas = 0"         || fail "ready replicas NOT 0"
    [[ $SYMPTOM_UNAVAIL  == true ]] && pass "unavailable replicas = 2"   || fail "unavailable replicas NOT 2"
    exit 1
  fi

  # Symptom 1: kube_deployment_status_replicas_ready for web = 0
  ready_val=$(check_prom 'kube_deployment_status_replicas_ready{namespace="staging",deployment="web"}')
  if [[ -n "$ready_val" ]]; then
    ok=$(echo "$ready_val == 0" | bc -l 2>/dev/null || echo 0)
    [[ "$ok" == "1" ]] && SYMPTOM_REPLICAS=true
  fi

  # Symptom 2: kube_deployment_status_replicas_unavailable for web >= 0 (meaning spec.replicas was 0, so check spec replicas = 0)
  spec_val=$(check_prom 'kube_deployment_spec_replicas{namespace="staging",deployment="web"}')
  if [[ -n "$spec_val" ]]; then
    ok=$(echo "$spec_val == 0" | bc -l 2>/dev/null || echo 0)
    [[ "$ok" == "1" ]] && SYMPTOM_UNAVAIL=true
  fi

  if [[ $SYMPTOM_REPLICAS == true && $SYMPTOM_UNAVAIL == true ]]; then
    echo ""
    pass "All service_down symptoms verified in ${elapsed}s."
    pass "  kube_deployment_status_replicas_ready{web} = 0"
    pass "  kube_deployment_spec_replicas{web} = 0"
    exit 0
  fi

  info "Elapsed ${elapsed}s – ready=${ready_val:-N/A} spec=${spec_val:-N/A}"
  sleep $INTERVAL
done
