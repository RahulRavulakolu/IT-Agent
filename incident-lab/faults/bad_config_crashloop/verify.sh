#!/usr/bin/env bash
# faults/bad_config_crashloop/verify.sh
# Poll Prometheus and kubectl for expected CrashLoopBackOff symptoms.
# Exits 0 if all symptoms appear within TIMEOUT_SECONDS, else exits 1.
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
  # Returns the scalar value of a PromQL instant query (empty if no data)
  local query=$1
  curl -sf "${PROM_URL}/api/v1/query" \
    --data-urlencode "query=${query}" 2>/dev/null \
    | jq -r '.data.result[0].value[1] // empty' 2>/dev/null || echo ""
}

check_loki() {
  local logql=$1
  local since="${2:-5m}"
  # Returns count of matching log lines in last $since
  local start_ns
  start_ns=$(date -d "-${since}" +%s%N 2>/dev/null || python3 -c "import time; print(int((time.time()-300)*1e9))")
  curl -sf "${LOKI_URL}/loki/api/v1/query_range" \
    --data-urlencode "query=${logql}" \
    --data-urlencode "start=${start_ns}" \
    --data-urlencode "limit=5" 2>/dev/null \
    | jq -r '.data.result | length' 2>/dev/null || echo "0"
}

echo "[verify:bad_config_crashloop] Polling for symptoms (timeout: ${TIMEOUT}s)..."
echo "  PROM: ${PROM_URL}"
echo "  LOKI: ${LOKI_URL}"
echo ""

SYMPTOM_RESTARTS=false
SYMPTOM_CRASHLOOP=false
SYMPTOM_LOG=false

start=$(date +%s)
while true; do
  now=$(date +%s)
  elapsed=$((now - start))
  if [[ $elapsed -ge $TIMEOUT ]]; then
    echo ""
    fail "TIMEOUT after ${TIMEOUT}s. Symptoms not fully observed."
    [[ $SYMPTOM_RESTARTS  == true ]] && pass "restart counter rising"   || fail "restart counter NOT rising"
    [[ $SYMPTOM_CRASHLOOP == true ]] && pass "CrashLoopBackOff detected" || fail "CrashLoopBackOff NOT detected"
    [[ $SYMPTOM_LOG       == true ]] && pass "ERROR log found in Loki"   || fail "ERROR log NOT found in Loki"
    exit 1
  fi

  # Symptom 1: Restart count > 0 for api pods
  restart_val=$(check_prom 'sum(kube_pod_container_status_restarts_total{namespace="staging",container="api"})')
  if [[ -n "$restart_val" ]] && (( $(echo "$restart_val > 0" | bc -l 2>/dev/null || echo 0) )); then
    SYMPTOM_RESTARTS=true
  fi

  # Symptom 2: Pod in CrashLoopBackOff (waiting reason)
  crashloop_count=$(kubectl get pods -n "$NS" -l app=api \
    -o jsonpath='{range .items[*]}{.status.containerStatuses[*].state.waiting.reason}{"\n"}{end}' 2>/dev/null \
    | grep -c "CrashLoopBackOff" || echo "0")
  if [[ "$crashloop_count" -gt 0 ]]; then
    SYMPTOM_CRASHLOOP=true
  fi

  # Symptom 3: ERROR log containing "invalid DATABASE_URL" in Loki
  log_count=$(check_loki '{namespace="staging",app="api"} |= "invalid DATABASE_URL"')
  if [[ "$log_count" -gt 0 ]]; then
    SYMPTOM_LOG=true
  fi

  if [[ $SYMPTOM_RESTARTS == true && $SYMPTOM_CRASHLOOP == true && $SYMPTOM_LOG == true ]]; then
    echo ""
    pass "All symptoms verified in ${elapsed}s:"
    pass "  restart counter > 0"
    pass "  CrashLoopBackOff state"
    pass "  ERROR 'invalid DATABASE_URL' in logs"
    exit 0
  fi

  info "Elapsed ${elapsed}s – restarts=${SYMPTOM_RESTARTS} crashloop=${SYMPTOM_CRASHLOOP} log=${SYMPTOM_LOG}"
  sleep $INTERVAL
done
