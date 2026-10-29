#!/usr/bin/env bash
# check-prereqs.sh – Validate all required tools are installed with minimum versions.
# Exits non-zero and prints exactly which tools are missing or too old.
set -euo pipefail

BOLD='\033[1m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
fail() { echo -e "${RED}[FAIL]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }

ERRORS=0

check_cmd() {
  local cmd=$1
  local hint=${2:-"Please install $cmd"}
  if ! command -v "$cmd" &>/dev/null; then
    fail "$cmd not found – $hint"
    ERRORS=$((ERRORS + 1))
    return 1
  fi
  ok "$cmd found at $(command -v "$cmd")"
  return 0
}

check_version_ge() {
  # check_version_ge <cmd> <got_version> <min_version> <friendly_name>
  local cmd=$1 got=$2 min=$3 name=$4
  if printf '%s\n%s\n' "$min" "$got" | sort -V -C; then
    ok "$name version $got >= $min"
  else
    fail "$name version $got is below minimum $min"
    ERRORS=$((ERRORS + 1))
  fi
}

echo -e "\n${BOLD}=== Incident Lab Prerequisite Check ===${NC}\n"

# --- docker ---
if check_cmd docker "See https://docs.docker.com/get-docker/"; then
  if ! docker info &>/dev/null; then
    fail "Docker daemon is not running. Please start Docker."
    ERRORS=$((ERRORS + 1))
  else
    ok "Docker daemon is running"
  fi
fi

# --- kind ---
if check_cmd kind "See https://kind.sigs.k8s.io/docs/user/quick-start/"; then
  KIND_VER=$(kind version | grep -oP '(?<=kind v)\S+' || echo "0.0.0")
  check_version_ge kind "$KIND_VER" "0.20.0" "kind"
fi

# --- kubectl ---
if check_cmd kubectl "See https://kubernetes.io/docs/tasks/tools/"; then
  KUBECTL_VER=$(kubectl version --client -o json 2>/dev/null | grep -oP '(?<="gitVersion": "v)\S+(?=")' | head -1 || echo "0.0.0")
  check_version_ge kubectl "$KUBECTL_VER" "1.28.0" "kubectl"
fi

# --- helm ---
if check_cmd helm "See https://helm.sh/docs/intro/install/"; then
  HELM_VER=$(helm version --short 2>/dev/null | grep -oP '(?<=v)\S+(?=\+)' || echo "0.0.0")
  check_version_ge helm "$HELM_VER" "3.14.0" "helm"
fi

# --- curl ---
check_cmd curl "Install with: sudo apt-get install curl  /  brew install curl"

# --- jq ---
check_cmd jq "Install with: sudo apt-get install jq  /  brew install jq"

# --- docker build (check for buildkit) ---
if command -v docker &>/dev/null && docker info &>/dev/null; then
  if docker buildx version &>/dev/null; then
    ok "docker buildx available (BuildKit enabled)"
  else
    warn "docker buildx not found – builds may be slower but will still work"
  fi
fi

echo ""
if [[ $ERRORS -gt 0 ]]; then
  echo -e "${RED}${BOLD}Prerequisite check FAILED – $ERRORS missing or misconfigured tool(s).${NC}"
  echo "Please fix the issues above and re-run: make up"
  exit 1
else
  echo -e "${GREEN}${BOLD}All prerequisites satisfied. Ready to build.${NC}"
fi
