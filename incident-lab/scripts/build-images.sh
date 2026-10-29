#!/usr/bin/env bash
# build-images.sh – Build all app images and load them into the kind cluster.
# Idempotent: rebuilding an existing image replaces it.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-incident-lab}"

info() { echo -e "\033[1;34m[build]\033[0m $*"; }
ok()   { echo -e "\033[0;32m[build]\033[0m $*"; }

# --- web ---
info "Building web:v1 ..."
docker build -t web:v1 "${REPO_ROOT}/apps/web"
ok "web:v1 built"
info "Loading web:v1 into kind cluster '${CLUSTER_NAME}' ..."
kind load docker-image web:v1 --name "${CLUSTER_NAME}"
ok "web:v1 loaded"

# --- api v1 (healthy) ---
info "Building api:v1 (healthy build) ..."
docker build --build-arg BUGGY_BUILD=false -t api:v1 "${REPO_ROOT}/apps/api"
ok "api:v1 built"
info "Loading api:v1 ..."
kind load docker-image api:v1 --name "${CLUSTER_NAME}"
ok "api:v1 loaded"

# --- api v2-bad (buggy) ---
info "Building api:v2-bad (buggy build – 70% 500s + 1.5s latency) ..."
docker build --build-arg BUGGY_BUILD=true -t api:v2-bad "${REPO_ROOT}/apps/api"
ok "api:v2-bad built"
info "Loading api:v2-bad ..."
kind load docker-image api:v2-bad --name "${CLUSTER_NAME}"
ok "api:v2-bad loaded"

# --- loadgen ---
info "Building loadgen:v1 ..."
docker build -t loadgen:v1 "${REPO_ROOT}/loadgen"
ok "loadgen:v1 built"
info "Loading loadgen:v1 ..."
kind load docker-image loadgen:v1 --name "${CLUSTER_NAME}"
ok "loadgen:v1 loaded"

echo ""
ok "All images built and loaded successfully."
