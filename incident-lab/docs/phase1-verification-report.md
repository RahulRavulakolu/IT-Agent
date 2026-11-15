# Phase 1 Verification Report: Monitoring & Alert Detection
**Project:** Autonomous IT Incident Resolution Agent (IT-Agent)  
**Phase under review:** Phase 1 – Monitoring & Alert Detection  
**Commit evaluated:** `46f48468fa55fef960ac0c0d0961ebb530b5ce4d` ("feat: implement Phase 1 alert ingestion")  
**Review date:** 2026-11-12  
**Reviewer:** Senior SRE & QA Engineer  
**Method:** Static code audit (Phase A) + runtime verification assessment (Phase B)

---

## Executive Summary

Phase 1 code was committed in `46f4846` adding:
1. `event-gateway/` — FastAPI service with `/api/v1/alerts`, `/api/v1/incidents`, `/healthz`, `/readyz`, `/metrics`
2. `incident-lab/observability/alert-rules/incident-lab-alerts.yaml` — PrometheusRule with 5 fault rule groups (8 alert definitions)
3. `incident-lab/observability/alertmanager-config.yaml` — AlertmanagerConfig CRD for webhook routing
4. `event-gateway/k8s/` — Kubernetes manifests for `event-gateway` in `monitoring` namespace
5. Makefile targets: `make gateway-up`, `make gateway-down`, `make gateway-test`, `make alerts-status`, `make incidents`

However, a rigorous SRE and QA audit identified **6 BLOCKING findings** and **4 NON-BLOCKING findings** that prevent Phase 1 from functioning reliably or being accepted:
1. **Critical architectural defect:** The Event Gateway writes to the staging application database (`db-service.staging.svc.cluster.local:5432/incidentlab`) instead of a separate, isolated database instance in `monitoring`.
2. **Prometheus Operator namespace isolation routing block:** `AlertmanagerConfig` CRD is in `monitoring`, but faults originate in `staging`. By default, Prometheus Operator injects a mandatory `namespace="monitoring"` matcher, causing all staging alerts to be silently dropped.
3. **Database connection concurrency bug:** A single global psycopg2 connection is shared across threads in `asyncio.run_in_executor`, leading to `InterfaceError` / transaction corruption under concurrent load.
4. **Race condition on deduplication:** `upsert_incident` uses read-then-write (`SELECT ... WHERE status='open'` followed by `INSERT`) without `ON CONFLICT DO UPDATE`. Concurrent webhooks with the same fingerprint throw `UniqueViolation`.
5. **Correlation logic not implemented:** `find_correlated_incidents` only logs a warning; it does not correlate or group related alerts into the same incident.
6. **No automated `make test-alerts` or CI:** No end-to-end alert verification target or GitHub Actions workflow exists.
7. **Runtime blocked:** The host machine lacks WSL2, preventing live cluster verification.

**Final Verdict: NOT ACCEPTED** (Requires fixes to blocking findings).

---

## Phase A: Static Audit

### A1. Alert Rules (`incident-lab/observability/alert-rules/incident-lab-alerts.yaml`)

| Check | Status | Evidence & Analysis |
|---|---|---|
| Covers all 5 faults | **PASS** | Exactly 1 `PrometheusRule` (`incident-lab-alerts`, namespace `monitoring`) covering all 5 faults across 5 rule groups (lines 18, 47, 89, 116, 173). |
| Rule definitions & metadata | **PASS** | All rules define name, expr, `for:`, `severity`, `fault_type`, `service`, `environment: staging`, and descriptive `summary`/`description` annotations. |
| Expressions match `meta.yaml` | **PASS** | `ApiCrashLoopBackOff` checks restart increase > 0 (`meta.yaml` restart count). `ApiDataVolumeFull` checks ratio > 0.85 (`meta.yaml` > 0.9). `WebServiceDown` checks replicas == 0 (`meta.yaml` == 0). `ApiOOMKilled` checks terminated reason == 1. `ApiBadDeploy` checks 5xx fraction > 0.30 (`meta.yaml` ~ 0.70). |
| False-positive risk at baseline | **PASS** | At baseline (clean staging), restarts = 0, tmpfs ratio < 0.10, web ready replicas = 2, OOMKills = 0, 5xx fraction = 0. No alerts fire at baseline. |
| Rules that can never fire | **FAIL (HIGH)** | `ApiMemoryNearLimit` (lines 149–157) divides `container_memory_working_set_bytes` (from cAdvisor) by `kube_pod_container_resource_limits` (from kube-state-metrics) without `on(pod, container, namespace)` vector matching. Because label sets differ between metric sources, binary division without `on(...)` yields an empty vector. This rule will never evaluate or fire. |
| Prometheus Operator selection | **PASS** | `metadata.labels` has `release: kps` (line 11). `kube-prometheus-stack-values.yaml` specifies `ruleSelectorNilUsesHelmValues: false`, `ruleSelector: {}`, and `ruleNamespaceSelector: {}` (lines 25–27). Operator selects this rule across namespaces. |

---

### A2. Alertmanager Configuration (`incident-lab/observability/alertmanager-config.yaml`)

| Check | Status | Evidence & Analysis |
|---|---|---|
| Webhook URL and path | **PASS** | Line 46: `http://event-gateway-service.monitoring.svc.cluster.local:8000/api/v1/alerts`. Matches `event-gateway/k8s/service.yaml` (name `event-gateway-service`, port 8000, namespace `monitoring`). |
| `send_resolved: true` | **PASS** | Line 47: `sendResolved: true`. |
| Route grouping & intervals | **PASS** | `groupBy: [alertname, service, environment]`, `groupWait: 30s` (10s for critical), `groupInterval: 5m` (1m for critical), `repeatInterval: 4h` (1h for critical). Dedup window buffers initial alerts for 30s before firing; updates repeat after 5m. |
| Alertmanager v4 webhook schema | **PASS** | `event-gateway/app/models.py` lines 111–140: `AlertmanagerWebhook` validates `version="4"`, `groupKey`, `status`, `receiver`, `alerts`, labels, annotations, startsAt, endsAt, fingerprint. |
| Route namespace filtering | **FAIL (BLOCKER)** | `AlertmanagerConfig` CRD is in `namespace: monitoring`. In Prometheus Operator, namespace-scoped `AlertmanagerConfig` resources automatically enforce a mandatory matcher `namespace="monitoring"`. Because the application and faults run in `namespace: staging`, Alertmanager drops all staging alerts and never routes them to `event-gateway`. Disabling this requires setting `alertmanagerSpec.alertmanagerConfiguration.alertmanagerConfigMatcherStrategy.type: None` in `kube-prometheus-stack-values.yaml` or deploying the route globally in values. |

---

### A3. Event Gateway Code (`event-gateway/app/`)

| Check | Status | Evidence & Analysis |
|---|---|---|
| Endpoints & validation | **PASS** | `POST /api/v1/alerts`, `GET /api/v1/incidents`, `GET /api/v1/incidents/{id}`, `GET /healthz`, `GET /readyz`, `GET /metrics`. `routes.py` lines 86–92 rejects invalid JSON with 400 and schema errors with 422 (never 500). |
| Fingerprint & deduplication | **PASS** | `models.py` lines 77–89 computes deterministic SHA-256 fingerprint over sorted label pairs if missing. Dedup uses `fingerprint` for lookup. |
| Correlation logic | **FAIL (HIGH)** | `routes.py` lines 146–160 and `repository.py` lines 211–236: `find_correlated_incidents` queries open incidents for the same `service:environment` within window, but **only logs a warning**. It does not attach alerts or group them into a single incident. Multiple alerts from the same fault (e.g. `ApiDataVolumeFull` + `ApiDataVolumeCritical`) produce separate incidents. |
| State machine transitions | **PASS** | States `open` and `resolved`. On `firing`, existing open incident is updated; on `resolved`, status is set to `resolved` with `resolved_at=NOW()`. A re-fire after resolve creates a new open incident. |
| Idempotency & Concurrency | **FAIL (BLOCKER)** | In `repository.py` lines 38–75, `upsert_incident` executes `SELECT ... WHERE status='open'`, and if none exists, executes `INSERT`. This is a non-atomic read-then-write. Under concurrent webhooks with the same fingerprint (e.g. 20 concurrent requests in B4), multiple threads execute `INSERT`, causing `psycopg2.errors.UniqueViolation` on `incidents_fingerprint_open_idx`. An atomic `INSERT ... ON CONFLICT` statement is required. |
| DB connection thread safety | **FAIL (BLOCKER)** | `connection.py` lines 30–42 uses a single global `_conn = None` without a pool. In `routes.py` line 105, `_process_payload` is executed in `loop.run_in_executor` (thread pool). Multiple threads accessing `_conn` concurrently produce `psycopg2.InterfaceError: connection already in transaction` and corrupted state. |
| Structured JSON logging | **PASS** | Configured via `python-json-logger` in `main.py` lines 37–52. Output contains `asctime`, `levelname`, `name`, `message`. |
| Health & readiness probes | **PASS** | `/healthz` returns 200 process-alive. `/readyz` executes `SELECT 1 FROM incidents LIMIT 1;` against DB and returns 503 if unreachable (`health.py` lines 20–37). |
| Secrets & configuration | **FAIL (MED)** | `connection.py` lines 25–28 hardcodes plaintext default credentials (`postgresql://labuser:labpass123@db-service:5432/incidentlab`). In `event-gateway/k8s/configmap.yaml` line 7, `DATABASE_URL` with password `labpass123` is stored in a ConfigMap rather than a Kubernetes Secret. |

---

### A4. Persistence and Migrations (`event-gateway/migrations/`, `event-gateway/app/db/`)

| Check | Status | Evidence & Analysis |
|---|---|---|
| Schema, constraints & indexes | **PASS** | `001_init.sql` creates `incidents` (BIGSERIAL PK, status, JSONB labels/annotations, correlation_key, timestamps) and `events` (FK to incidents.id ON DELETE CASCADE). Includes partial unique index `incidents_fingerprint_open_idx` on `(fingerprint) WHERE status = 'open'`. |
| Versioned idempotent migrations | **FAIL (MED)** | Schema is applied via inline/file execution at startup (`connection.py` lines 59–79). There is **no migration version table** (`schema_migrations`), no tracking of which migration has run, and no rollback mechanism. |
| **Separate Postgres instance** | **FAIL (BLOCKER)** | In `event-gateway/k8s/configmap.yaml` line 7: `DATABASE_URL: "postgresql://labuser:labpass123@db-service.staging.svc.cluster.local:5432/incidentlab"`. The gateway shares the exact same PostgreSQL database as the `staging` application! If `staging` DB crashes, fails, or is misconfigured (e.g. `bad_config_crashloop`), incident storage is simultaneously disabled. The incident store **must** use an independent PostgreSQL instance in `monitoring`. |

---

### A5. Kubernetes Deployment of the Gateway (`event-gateway/k8s/`, `incident-lab/Makefile`)

| Check | Status | Evidence & Analysis |
|---|---|---|
| Manifests present | **PASS** | `deployment.yaml`, `service.yaml`, `configmap.yaml`, `servicemonitor.yaml`, `kustomization.yaml` all defined in `monitoring` namespace. |
| Pinned image & resources | **PASS** | `image: event-gateway:v1`, `imagePullPolicy: IfNotPresent`. Requests: 100m CPU / 128Mi RAM; limits: 500m CPU / 256Mi RAM. |
| Liveness/readiness probes | **PASS** | Configured on `/healthz` and `/readyz` with 5s delay, 10s period. |
| Deployed automatically | **PASS** | `incident-lab/Makefile` line 61 includes `gateway-up` in `up:` target. `make up` builds `event-gateway:v1` via `scripts/build-images.sh` and applies manifests. |
| Idempotency | **PASS** | `kubectl apply -k` and `kubectl rollout status` are safe to run repeatedly. |

---

### A6. Docs and Automation

| Check | Status | Evidence & Analysis |
|---|---|---|
| README documentation | **PASS** | `incident-lab/README.md` lines 59–69 documents `make alerts-status`, `make incidents`, `make gateway-up`, `make gateway-test`. |
| Machine-specific paths | **FAIL (LOW)** | `incident-lab/README.md` lines 19–20: hardcodes `c:\IT agent\incident-lab (Windows) ≡ /mnt/c/IT agent/incident-lab (WSL2)` and `cd /mnt/c/IT\ agent/incident-lab`. |
| Gateway unit/integration tests | **PASS** | `event-gateway/tests/test_models.py` and `test_routes.py` test validation, fingerprint generation, dedup, and resolution. |
| Automated alert verification script | **FAIL (BLOCKER)** | Makefile lacks a `make test-alerts` target that injects each fault, asserts an incident, resets, and asserts resolution. |
| CI workflow | **FAIL (MED)** | Repository has no `.github/workflows/ci.yml`. |

---

## Phase B: Runtime Verification

**Status: UNVERIFIED (Environment Blocked)**

### Environmental Block:
Running `wsl -l -v` confirmed:
```
The Windows Subsystem for Linux is not installed.
```
Because `kind`, `kubectl`, `helm`, and `docker` are Linux binaries that require WSL2 or a native Linux environment, the cluster cannot be started from this PowerShell host.

| Check | Status | Reason |
|---|---|---|
| B1. Baseline (5 min load, 0 firing alerts, 0 incidents) | **UNVERIFIED** | Host lacks WSL2 / Docker / kind runtime |
| B2. Rule loading & Alertmanager status | **UNVERIFIED** | Host lacks WSL2 / Docker / kind runtime |
| B3. End-to-end per fault (5 faults) | **UNVERIFIED** | Host lacks WSL2 / Docker / kind runtime |
| B4. Resilience & concurrency (20 parallel webhooks) | **UNVERIFIED** | Host lacks WSL2 / Docker / kind runtime |
| B5. Direct database inspection | **UNVERIFIED** | Host lacks WSL2 / Docker / kind runtime |

---

## Summary Scorecard

| Check | Category | Result | Severity |
|---|---|---|---|
| A1. Alert rules (coverage & PromQL) | Static | PASS | — |
| A1. PromQL Vector Division (`ApiMemoryNearLimit`) | Static | FAIL | HIGH |
| A2. Alertmanager Webhook Receiver & Schema | Static | PASS | — |
| A2. AlertmanagerConfig Namespace Isolation | Static | FAIL | BLOCKER |
| A3. Gateway Endpoints & Validation | Static | PASS | — |
| A3. Correlation Logic Grouping | Static | FAIL | HIGH |
| A3. Dedup Race Condition (`INSERT` vs `UPSERT`) | Static | FAIL | BLOCKER |
| A3. DB Connection Thread Safety (no pool) | Static | FAIL | BLOCKER |
| A3. Secrets in ConfigMap & Hardcoded Fallback | Static | FAIL | MED |
| A4. Database Schema & Tables | Static | PASS | — |
| A4. Versioned Migration Table | Static | FAIL | MED |
| A4. Dedicated Postgres Instance Isolation | Static | FAIL | BLOCKER |
| A5. Kubernetes Deployment Manifests | Static | PASS | — |
| A6. Machine-Specific Paths in Docs | Static | FAIL | LOW |
| A6. Automated `make test-alerts` Target | Static | FAIL | BLOCKER |
| A6. CI Workflow (`.github/workflows`) | Static | FAIL | MED |
| B1–B5. Runtime Verification Suite | Runtime | UNVERIFIED | BLOCKER (Env) |

---

## Findings List

### F-P1-001: Gateway Shares Target Application Database in Staging (BLOCKER)
- **Severity:** HIGH / BLOCKER
- **Evidence:** `event-gateway/k8s/configmap.yaml` line 7:
  `DATABASE_URL: "postgresql://labuser:labpass123@db-service.staging.svc.cluster.local:5432/incidentlab"`.
- **Why it matters for AI agent:** The incident store must observe failures, not participate in them. When `bad_config_crashloop` occurs or PostgreSQL in staging is degraded, the gateway cannot record or update incidents. The AI agent loses its perception plane.
- **Recommended fix:** Deploy a dedicated `incident-db` PostgreSQL StatefulSet in `namespace: monitoring`, accessed via Kubernetes Secret `incident-db-secret`.

---

### F-P1-002: AlertmanagerConfig Namespaced Matcher Drops Staging Alerts (BLOCKER)
- **Severity:** HIGH / BLOCKER
- **Evidence:** `incident-lab/observability/alertmanager-config.yaml` is deployed in `namespace: monitoring`. Prometheus Operator injects a mandatory matcher `namespace="monitoring"`. All 5 faults run in `staging` with label `namespace="staging"`.
- **Why it matters for AI agent:** Alertmanager will never forward alerts from staging to `event-gateway`. Zero incidents will be created.
- **Recommended fix:** In `kube-prometheus-stack-values.yaml`, set `alertmanager.alertmanagerSpec.alertmanagerConfiguration.alertmanagerConfigMatcherStrategy.type: None` or embed the webhook route directly in `kube-prometheus-stack-values.yaml` under `alertmanager.config`.

---

### F-P1-003: Database Connection Pool Missing — Race Condition on Concurrent Requests (BLOCKER)
- **Severity:** HIGH / BLOCKER
- **Evidence:** `event-gateway/app/db/connection.py` lines 30–42 uses a single global `_conn` object. In `routes.py` line 105, `_process_payload` is executed in `run_in_executor` threads.
- **Why it matters for AI agent:** When Alertmanager delivers a batch of alerts or concurrent webhooks arrive, concurrent threads share the same un-pooled connection, throwing `psycopg2.InterfaceError: connection already in transaction` and crashing ingestion.
- **Recommended fix:** Replace `_conn` with `psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=10)`.

---

### F-P1-004: Deduplication Uses Read-Then-Write Instead of Atomic Upsert (BLOCKER)
- **Severity:** HIGH / BLOCKER
- **Evidence:** `event-gateway/app/db/repository.py` lines 38–75 executes `SELECT` then `INSERT`. Under concurrent requests, two threads see no open incident and both execute `INSERT`, triggering `psycopg2.errors.UniqueViolation` on `incidents_fingerprint_open_idx`.
- **Why it matters for AI agent:** Alertmanager frequently retries or sends multiple alerts in parallel bursts. The gateway will fail with 500 / unhandled exceptions instead of cleanly deduplicating.
- **Recommended fix:** Use PostgreSQL `INSERT INTO incidents ... ON CONFLICT (fingerprint) WHERE status = 'open' DO UPDATE SET ... RETURNING id`.

---

### F-P1-005: PromQL Vector Arithmetic in `ApiMemoryNearLimit` Yields Empty Vector (HIGH)
- **Severity:** HIGH
- **Evidence:** `incident-lab/observability/alert-rules/incident-lab-alerts.yaml` lines 149–157:
  `container_memory_working_set_bytes{...} / kube_pod_container_resource_limits{...} > 0.80`
- **Why it matters for AI agent:** The metric from cAdvisor and the metric from kube-state-metrics have mismatched label dimensions (`resource="memory"`, `node`, `image`). Without `on(pod, container, namespace)` vector matching, Prometheus returns an empty set. The alert never fires.
- **Recommended fix:** Rewrite the expression using vector matching:
  ```promql
  (
    container_memory_working_set_bytes{namespace="staging", container="api"}
    / on(pod, container, namespace)
    kube_pod_container_resource_limits{namespace="staging", container="api", resource="memory"}
  ) > 0.80
  ```

---

### F-P1-006: Correlation Only Logs Warnings — Alerts Are Not Linked (HIGH)
- **Severity:** HIGH
- **Evidence:** `event-gateway/app/api/routes.py` lines 146–160: `correlated = repository.find_correlated_incidents(...)` only logs a warning; it does not associate or group alerts into a single incident entity.
- **Why it matters for AI agent:** Multi-signal incidents (e.g. `disk_full` triggering both `ApiDataVolumeFull` and `ApiDataVolumeCritical`, or `oom_kill` triggering restarts + OOM) spawn multiple separate incidents instead of a consolidated incident dossier for the AI agent to investigate.
- **Recommended fix:** When open incidents for the same `service:environment` exist within the correlation window, attach incoming alerts to the existing incident's event history or record the `parent_incident_id`.

---

### F-P1-007: Missing Automated `make test-alerts` Target (BLOCKER)
- **Severity:** HIGH / BLOCKER
- **Evidence:** `incident-lab/Makefile` contains `test-faults` for Phase 0, but no `test-alerts` target that verifies the end-to-end alert pipeline.
- **Recommended fix:** Provide `incident-lab/scripts/test-alerts.sh` and wire it to `make test-alerts`.

---

### F-P1-008: Missing Migration Tracking Table (MED)
- **Severity:** MEDIUM
- **Evidence:** `event-gateway/migrations/001_init.sql` lacks a `schema_migrations` table.
- **Recommended fix:** Add a `schema_migrations (version int primary key, applied_at timestamptz)` table to track schema versions idempotently.

---

### F-P1-009: Database Password in Plaintext ConfigMap (MED)
- **Severity:** MEDIUM
- **Evidence:** `event-gateway/k8s/configmap.yaml` stores `DATABASE_URL` with password `labpass123`.
- **Recommended fix:** Move database credentials to a Kubernetes Secret (`incident-db-secret`).

---

### F-P1-010: Missing CI Workflow (MED)
- **Severity:** MEDIUM
- **Evidence:** No `.github/workflows/` directory in repository.
- **Recommended fix:** Add `.github/workflows/ci.yml` running linting (`ruff`) and unit tests (`pytest`).

---

## Verdict

### **NOT ACCEPTED**

Phase 1 cannot be accepted in its current state. The 6 blocking findings (F-P1-001, F-P1-002, F-P1-003, F-P1-004, F-P1-007, and runtime testability) must be resolved to establish a robust, reliable monitoring and incident detection platform for subsequent AI agent phases.
