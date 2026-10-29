#!/usr/bin/env bash
# ports.sh – Start or stop kubectl port-forwards for all lab services.
# Usage:
#   scripts/ports.sh         → start all port-forwards in background
#   scripts/ports.sh stop    → kill all port-forwards started by this script
set -euo pipefail

PID_DIR="/tmp/incident-lab-ports"
NS="staging"
MON_NS="monitoring"

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

start_forward() {
  local name=$1 ns=$2 resource=$3 local_port=$4 remote_port=$5
  local pid_file="${PID_DIR}/${name}.pid"

  # Kill existing forward for this slot
  if [[ -f "$pid_file" ]]; then
    old_pid=$(cat "$pid_file")
    if kill -0 "$old_pid" 2>/dev/null; then
      kill "$old_pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
  fi

  kubectl port-forward -n "$ns" "$resource" "${local_port}:${remote_port}" \
    --address 127.0.0.1 &>/tmp/incident-lab-pf-${name}.log &
  local pid=$!
  echo "$pid" > "$pid_file"
  echo -e "${GREEN}[ports]${NC} ${name}: 127.0.0.1:${local_port} → ${resource}:${remote_port} (pid ${pid})"
}

start_all() {
  mkdir -p "$PID_DIR"
  echo -e "${BOLD}Starting port-forwards...${NC}"

  # Grafana (find the pod or use service)
  start_forward grafana  "$MON_NS" "svc/kps-grafana"               3000 80
  # Prometheus
  start_forward prom     "$MON_NS" "svc/kps-kube-prometheus-stack-prometheus" 9090 9090
  # Loki
  start_forward loki     "$MON_NS" "svc/loki-gateway"              3100 80
  # web
  start_forward web      "$NS"     "svc/web-service"               8080 80
  # api  (direct access for debugging)
  start_forward api      "$NS"     "svc/api-service"               8081 80

  echo ""
  echo -e "${BOLD}Port-forwards active:${NC}"
  echo "  Grafana:    http://127.0.0.1:3000  (admin/admin)"
  echo "  Prometheus: http://127.0.0.1:9090"
  echo "  Loki:       http://127.0.0.1:3100"
  echo "  web:        http://127.0.0.1:8080"
  echo "  api:        http://127.0.0.1:8081"
  echo ""
  echo "Stop with: scripts/ports.sh stop"
}

stop_all() {
  echo -e "${YELLOW}[ports]${NC} Stopping port-forwards..."
  for pid_file in "${PID_DIR}"/*.pid; do
    [[ -f "$pid_file" ]] || continue
    pid=$(cat "$pid_file")
    name=$(basename "$pid_file" .pid)
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null && echo "  killed $name (pid $pid)" || true
    fi
    rm -f "$pid_file"
  done
  echo -e "${YELLOW}[ports]${NC} All port-forwards stopped."
}

case "${1:-start}" in
  stop)  stop_all ;;
  start) start_all ;;
  *)     echo "Usage: $0 [start|stop]"; exit 1 ;;
esac
