################################################################################
# Incident Lab – Makefile
# Idempotent: all targets are safe to run multiple times.
################################################################################

SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c

CLUSTER_NAME  := incident-lab
NAMESPACE     := staging
REPO_ROOT     := $(shell pwd)
SCRIPTS       := $(REPO_ROOT)/scripts
FAULTS_DIR    := $(REPO_ROOT)/faults

# Prometheus / Loki URLs (used by verify scripts)
export PROM_URL       := http://127.0.0.1:9090
export LOKI_URL       := http://127.0.0.1:3100
export NAMESPACE      := $(NAMESPACE)
export CLUSTER_NAME   := $(CLUSTER_NAME)

# Helm chart versions – pinned
HELM_KPS_VERSION       := 61.3.2
HELM_LOKI_VERSION      := 6.6.2
HELM_PROMTAIL_VERSION  := 6.16.4
HELM_PG_EXP_VERSION    := 0.15.0

# Fault IDs
FAULTS := bad_config_crashloop disk_full service_down oom_kill bad_deploy

.PHONY: help up down status ports load-start load-stop \
        inject verify reset reset-all test-faults \
        _cluster _namespaces _observability _app _loadgen

## ── Default target ────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "Incident Lab – available targets:"
	@echo ""
	@echo "  make up              Create cluster, install stack, deploy app, start load"
	@echo "  make down            Delete everything (cluster + local state)"
	@echo "  make status          Health summary of all components"
	@echo "  make ports           Start port-forwards (Grafana, Prom, Loki, web, api)"
	@echo "  make load-start      Scale loadgen to 1 replica"
	@echo "  make load-stop       Scale loadgen to 0 replicas"
	@echo ""
	@echo "  make inject FAULT=<id>  Inject a fault"
	@echo "  make verify FAULT=<id>  Verify fault symptoms (needs port-forwards)"
	@echo "  make reset  FAULT=<id>  Restore baseline after a fault"
	@echo "  make reset-all          Reset all faults to baseline"
	@echo "  make test-faults        Run inject+verify+reset for every fault; print table"
	@echo ""
	@echo "  Faults: $(FAULTS)"
	@echo ""

## ── Full stack up ─────────────────────────────────────────────────────────────
up: _prereqs _cluster _namespaces _images _observability _app _loadgen
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════╗"
	@echo "║  Incident Lab is UP  ✓                                   ║"
	@echo "║  Run: make ports   →  start port-forwards                ║"
	@echo "║  Run: make status  →  health summary                     ║"
	@echo "╚══════════════════════════════════════════════════════════╝"

_prereqs:
	@echo "=== [M0] Checking prerequisites ==="
	@bash $(SCRIPTS)/check-prereqs.sh

_cluster:
	@echo "=== [M1] Creating kind cluster '$(CLUSTER_NAME)' ==="
	@if kind get clusters 2>/dev/null | grep -q "^$(CLUSTER_NAME)$$"; then \
	  echo "[cluster] Cluster '$(CLUSTER_NAME)' already exists – skipping."; \
	else \
	  kind create cluster --config $(REPO_ROOT)/cluster/kind-config.yaml; \
	  echo "[cluster] Cluster created."; \
	fi
	@kubectl cluster-info --context kind-$(CLUSTER_NAME)

_namespaces:
	@echo "=== [M1] Applying namespaces ==="
	@kubectl apply -f $(REPO_ROOT)/cluster/namespaces.yaml

_images:
	@echo "=== [M2] Building and loading Docker images ==="
	@bash $(SCRIPTS)/build-images.sh

_observability:
	@echo "=== [M3] Installing observability stack via Helm ==="
	@kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
	@helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
	@helm repo add grafana https://grafana.github.io/helm-charts 2>/dev/null || true
	@helm repo update
	@echo "[obs] Installing/upgrading kube-prometheus-stack $(HELM_KPS_VERSION)..."
	@helm upgrade --install kps prometheus-community/kube-prometheus-stack \
	  --version $(HELM_KPS_VERSION) \
	  --namespace monitoring \
	  --values $(REPO_ROOT)/observability/kube-prometheus-stack-values.yaml \
	  --wait --timeout 10m
	@echo "[obs] Installing/upgrading Loki $(HELM_LOKI_VERSION)..."
	@helm upgrade --install loki grafana/loki \
	  --version $(HELM_LOKI_VERSION) \
	  --namespace monitoring \
	  --values $(REPO_ROOT)/observability/loki-values.yaml \
	  --wait --timeout 5m
	@echo "[obs] Installing/upgrading Promtail $(HELM_PROMTAIL_VERSION)..."
	@helm upgrade --install promtail grafana/promtail \
	  --version $(HELM_PROMTAIL_VERSION) \
	  --namespace monitoring \
	  --values $(REPO_ROOT)/observability/promtail-values.yaml \
	  --wait --timeout 3m
	@echo "[obs] Installing/upgrading postgres-exporter $(HELM_PG_EXP_VERSION)..."
	@helm upgrade --install postgres-exporter prometheus-community/prometheus-postgres-exporter \
	  --version $(HELM_PG_EXP_VERSION) \
	  --namespace monitoring \
	  --values $(REPO_ROOT)/observability/postgres-exporter-values.yaml \
	  --wait --timeout 3m
	@echo "[obs] Applying ServiceMonitors..."
	@kubectl apply -f $(REPO_ROOT)/observability/servicemonitors/app-servicemonitors.yaml
	@echo "[obs] Applying Grafana dashboard ConfigMap..."
	@kubectl apply -f $(REPO_ROOT)/observability/dashboards/incident-lab-overview.yaml
	@echo "[obs] Observability stack ready."

_app:
	@echo "=== [M2] Deploying application (db, api, web) ==="
	@echo "[app] Applying db..."
	@kubectl apply -k $(REPO_ROOT)/apps/db/k8s
	@echo "[app] Waiting for db StatefulSet to be ready..."
	@kubectl rollout status statefulset/db -n $(NAMESPACE) --timeout=120s
	@echo "[app] Applying api..."
	@kubectl apply -k $(REPO_ROOT)/apps/api/k8s/base
	@echo "[app] Applying web..."
	@kubectl apply -k $(REPO_ROOT)/apps/web/k8s/base
	@echo "[app] Waiting for api and web rollouts..."
	@kubectl rollout status deployment/api -n $(NAMESPACE) --timeout=120s
	@kubectl rollout status deployment/web -n $(NAMESPACE) --timeout=120s
	@echo "[app] Application deployed. Waiting for full health..."
	@bash $(SCRIPTS)/wait-healthy.sh $(NAMESPACE) 180

_loadgen:
	@echo "=== [M4] Starting load generator ==="
	@kubectl apply -f $(REPO_ROOT)/loadgen/k8s/deployment.yaml
	@kubectl rollout status deployment/loadgen -n $(NAMESPACE) --timeout=60s
	@echo "[loadgen] Load generator running (~5 req/s to web)."

## ── Tear down ─────────────────────────────────────────────────────────────────
down:
	@echo "=== Deleting kind cluster '$(CLUSTER_NAME)' ==="
	@bash $(SCRIPTS)/ports.sh stop 2>/dev/null || true
	@kind delete cluster --name $(CLUSTER_NAME) 2>/dev/null && \
	  echo "[down] Cluster deleted." || \
	  echo "[down] Cluster was not running."

## ── Status summary ────────────────────────────────────────────────────────────
status:
	@echo ""
	@echo "=== Cluster nodes ==="
	@kubectl get nodes -o wide 2>/dev/null || echo "(cluster not running)"
	@echo ""
	@echo "=== Pods – staging ==="
	@kubectl get pods -n staging -o wide 2>/dev/null || true
	@echo ""
	@echo "=== Pods – monitoring ==="
	@kubectl get pods -n monitoring -o wide 2>/dev/null || true
	@echo ""
	@echo "=== Deployments – staging ==="
	@kubectl get deployments -n staging 2>/dev/null || true
	@echo ""
	@echo "=== Helm releases ==="
	@helm list -n monitoring 2>/dev/null || true

## ── Port-forwards ─────────────────────────────────────────────────────────────
ports:
	@bash $(SCRIPTS)/ports.sh start

ports-stop:
	@bash $(SCRIPTS)/ports.sh stop

## ── Load generator controls ───────────────────────────────────────────────────
load-start:
	@kubectl scale deployment/loadgen -n $(NAMESPACE) --replicas=1
	@echo "[load] Load generator started."

load-stop:
	@kubectl scale deployment/loadgen -n $(NAMESPACE) --replicas=0
	@echo "[load] Load generator stopped."

## ── Fault injection ───────────────────────────────────────────────────────────
inject:
ifndef FAULT
	$(error "Usage: make inject FAULT=<fault_id>. Available: $(FAULTS)")
endif
	@if [[ ! -d "$(FAULTS_DIR)/$(FAULT)" ]]; then \
	  echo "ERROR: Unknown fault '$(FAULT)'. Available: $(FAULTS)"; exit 1; \
	fi
	@echo "=== Injecting fault: $(FAULT) ==="
	@bash $(FAULTS_DIR)/$(FAULT)/inject.sh

verify:
ifndef FAULT
	$(error "Usage: make verify FAULT=<fault_id>. Available: $(FAULTS)")
endif
	@if [[ ! -d "$(FAULTS_DIR)/$(FAULT)" ]]; then \
	  echo "ERROR: Unknown fault '$(FAULT)'. Available: $(FAULTS)"; exit 1; \
	fi
	@echo "=== Verifying fault: $(FAULT) ==="
	@bash $(FAULTS_DIR)/$(FAULT)/verify.sh

reset:
ifndef FAULT
	$(error "Usage: make reset FAULT=<fault_id>. Available: $(FAULTS)")
endif
	@if [[ ! -d "$(FAULTS_DIR)/$(FAULT)" ]]; then \
	  echo "ERROR: Unknown fault '$(FAULT)'. Available: $(FAULTS)"; exit 1; \
	fi
	@echo "=== Resetting fault: $(FAULT) ==="
	@bash $(FAULTS_DIR)/$(FAULT)/reset.sh

## ── Reset all ─────────────────────────────────────────────────────────────────
reset-all:
	@echo "=== Resetting ALL faults to baseline ==="
	@for fault in $(FAULTS); do \
	  echo "--- Resetting $$fault ---"; \
	  bash $(FAULTS_DIR)/$$fault/reset.sh 2>/dev/null || \
	    echo "WARN: $$fault reset had errors (may already be clean)"; \
	done
	@echo "[reset-all] Waiting for full staging health..."
	@bash $(SCRIPTS)/wait-healthy.sh $(NAMESPACE) 180
	@echo "[reset-all] All faults reset."

## ── Full test suite ───────────────────────────────────────────────────────────
test-faults:
	@echo ""
	@echo "=== Running full fault test suite ==="
	@echo ""
	@PASS=0; FAIL=0; RESULTS=""; \
	for fault in $(FAULTS); do \
	  echo ""; \
	  echo "────────────────────────────────────────"; \
	  echo "  Testing fault: $$fault"; \
	  echo "────────────────────────────────────────"; \
	  echo "  [1/4] Resetting to baseline..."; \
	  bash $(SCRIPTS)/wait-healthy.sh $(NAMESPACE) 180 || true; \
	  bash $(FAULTS_DIR)/$$fault/reset.sh 2>/dev/null || true; \
	  bash $(SCRIPTS)/wait-healthy.sh $(NAMESPACE) 180; \
	  echo "  [2/4] Injecting fault..."; \
	  bash $(FAULTS_DIR)/$$fault/inject.sh; \
	  echo "  [3/4] Verifying symptoms..."; \
	  if bash $(FAULTS_DIR)/$$fault/verify.sh; then \
	    echo "  [4/4] Resetting..."; \
	    bash $(FAULTS_DIR)/$$fault/reset.sh; \
	    bash $(SCRIPTS)/wait-healthy.sh $(NAMESPACE) 180; \
	    PASS=$$((PASS+1)); \
	    RESULTS="$$RESULTS\n  ✓ PASS  $$fault"; \
	  else \
	    echo "  [4/4] Verify FAILED – resetting anyway..."; \
	    bash $(FAULTS_DIR)/$$fault/reset.sh 2>/dev/null || true; \
	    FAIL=$$((FAIL+1)); \
	    RESULTS="$$RESULTS\n  ✗ FAIL  $$fault"; \
	  fi; \
	done; \
	echo ""; \
	echo "════════════════════════════════════════"; \
	echo "  Fault Test Results"; \
	echo "════════════════════════════════════════"; \
	echo -e "$$RESULTS"; \
	echo ""; \
	echo "  PASSED: $$PASS / 5"; \
	echo "  FAILED: $$FAIL / 5"; \
	echo "════════════════════════════════════════"; \
	if [[ $$FAIL -gt 0 ]]; then exit 1; fi
