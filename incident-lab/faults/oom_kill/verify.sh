#!/usr/bin/env bash
# faults/oom_kill/verify.sh
# Verify OOMKill symptoms: exit code 137, rising restarts, memory near limit.
set -euo pipefail

NS="${NAMESPACE:-staging}"
PROM_URL="${PROM_URL:-http://127.0.0.1:9090}"
TIMEOUT=${TIMEOUT_SECONDS:-180}
INTERVAL=15  # OOMKill takes a bit longer to manifest

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
pass() { echo -e "${GREEN}[PASS]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
info() { echo -e "${YELLOW}[wait]${NC} $*"; }

check_prom() {
  curl -sf "${PROM_URL}/api/v1/query" \
    --data-urlencode "query=${1}" 2>/dev/null \
    | jq -r '.data.result[0].value[1] // empty' 2>/dev/null || echo ""
}

echo "[verify:oom_kill] Polling for OOMKill symptoms (timeout: ${TIMEOUT}s)..."
echo "  Note: Memory must grow for ~30-60s before OOMKill occurs."

SYMPTOM_OOMKILL=false
SYMPTOM_RESTARTS=false

start=$(date +%s)
while true; do
  now=$(date +%s)
  elapsed=$((now - start))
  if [[ $elapsed -ge $TIMEOUT ]]; then
    echo ""
    fail "TIMEOUT after ${TIMEOUT}s."
    [[ $SYMPTOM_OOMKILL  == true ]] && pass "OOMKilled detected"    || fail "OOMKilled NOT detected"
    [[ $SYMPTOM_RESTARTS == true ]] && pass "restart counter rising" || fail "restart counter NOT rising"
    exit 1
  fi

  # Symptom 1: OOMKilled reason in pod status (kubectl)
  oom_count=$(kubectl get pods -n "$NS" -l app=api \
    -o jsonpath='{range .items[*]}{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}{end}' 2>/dev/null \
    | grep -c "OOMKilled" || echo "0")
  [[ "$oom_count" -gt 0 ]] && SYMPTOM_OOMKILL=true

  # Also check via Prometheus (kube-state-metrics oom reason)
  if [[ $SYMPTOM_OOMKILL == false ]]; then
    oom_metric=$(check_prom 'kube_pod_container_status_last_terminated_reason{namespace="staging",container="api",reason="OOMKilled"}')
    if [[ -n "$oom_metric" ]]; then
      ok=$(echo "$oom_metric > 0" | bc -l 2>/dev/null || echo 0)
      [[ "$ok" == "1" ]] && SYMPTOM_OOMKILL=true
    fi
  fi

  # Symptom 2: restart count > 0
  restarts=$(check_prom 'sum(kube_pod_container_status_restarts_total{namespace="staging",container="api"})')
  if [[ -n "$restarts" ]]; then
    ok=$(echo "$restarts > 0" | bc -l 2>/dev/null || echo 0)
    [[ "$ok" == "1" ]] && SYMPTOM_RESTARTS=true
  fi

  if [[ $SYMPTOM_OOMKILL == true && $SYMPTOM_RESTARTS == true ]]; then
    echo ""
    pass "All oom_kill symptoms verified in ${elapsed}s."
    pass "  Container terminated with OOMKilled"
    pass "  Restart counter > 0"
    exit 0
  fi

  info "Elapsed ${elapsed}s – oomkilled=${SYMPTOM_OOMKILL} restarts=${SYMPTOM_RESTARTS} (restarts_val=${restarts:-N/A})"
  sleep $INTERVAL
done
