# Autonomous IT Incident Resolution Agent (IT-Agent)

An autonomous IT incident resolution system designed to detect, investigate, remediate, and verify operational incidents in modern cloud-native environments.

---

## Project Roadmap

- [x] **Phase 0 – Incident Lab Sandbox (`incident-lab/`)**
  - Reproducible local Kubernetes (kind) sandbox
  - 3-tier microservice architecture (`web`, `api`, `db` + `loadgen`)
  - Full observability stack (Prometheus, Grafana, Loki, Promtail, Postgres-Exporter)
  - 5 deterministic fault injection & verification scenarios
- [x] **Phase 1 – Monitoring & Alert Detection**
  - Prometheus alert rules for all 5 incident fault types
  - Alertmanager webhook routing with deduplication and correlation
  - FastAPI Event Gateway (`event-gateway/`) with PostgreSQL persistence and schema migrations
  - Liveness/readiness health probes and structured JSON logging
- [ ] **Phase 2 – Investigation & Root Cause Analysis (RAG + Agentic Tools)**
  - Runbook vector search, log pattern matching, metric correlation
- [ ] **Phase 3 – Autonomous Remediation & Verification**
  - Safe automated rollback, config patch, and resource remediation
- [ ] **Phase 4 – Multi-Agent Orchestration & Closed-Loop Resolution**
  - End-to-end incident lifecycle management with LangGraph / MCP

---

## Phase 0: Incident Lab Sandbox

All Phase 0 sandbox code, fault injection scripts, observability configurations, and runbooks are located in [`incident-lab/`](./incident-lab/).

### Quickstart

```bash
cd incident-lab

# 1. Bring up the cluster, apps, observability stack, and baseline load
make up

# 2. Start port-forwards
make ports

# 3. Open dashboards
#    Grafana:    http://localhost:3000 (admin / admin)
#    Prometheus: http://localhost:9090
#    Loki:       http://localhost:3100

# 4. Inject, verify, and reset faults
make inject FAULT=disk_full
make verify FAULT=disk_full
make reset  FAULT=disk_full

# 5. Run full automated test suite across all 5 fault scenarios
make test-faults

# 6. Phase 1: View active alerts & ingested incidents
make alerts-status
make incidents
#    Event Gateway API: http://127.0.0.1:8000/api/v1/incidents
#    Swagger Docs:     http://127.0.0.1:8000/docs
```

For complete documentation on cluster topology, observability pipelines, fault catalog, and troubleshooting, see the [Incident Lab Documentation](./incident-lab/README.md) and [Fault Catalog](./incident-lab/docs/fault-catalog.md).
