# Phase 3 prompt: Tool gateway (MCP)

> How to use: make sure AGENTS.md is in the repo root, then paste everything
> below the line into your coding assistant.
> Gate before moving on: all five faults can be fixed by hand through the
> tools with a dev token, and every forged-token or out-of-bounds call is refused.

---

Phase 3: Tool gateway (MCP) with read tools, guarded write tools and config snapshots. Follow AGENTS.md.
Prerequisite: Phase 2 accepted.

Goal: the only interface the agent will ever use to observe or change the system. Safety here is enforced by code and Kubernetes RBAC, not by prompts.

1. Service
- tools/ package; `tool-gateway` runs in-cluster (namespace monitoring) as a Deployment with its own ServiceAccount. Expose MCP (official Python mcp SDK, streamable HTTP) plus a plain Python interface for tests. Bearer-token auth from a Secret. Port-forward 8100 via scripts/ports.sh.
- Least-privilege RBAC (Role/RoleBinding, no ClusterRole unless unavoidable): get/list pods, pods/log, deployments, replicasets, events, configmaps; patch deployments and scale; pods/exec ONLY in staging. No access to Secrets. Prove it with `kubectl auth can-i --list --as=system:serviceaccount:monitoring:tool-gateway -n staging` and the same for prod and monitoring; save the output as evidence.

2. Read tools (all return structured JSON with a UTC timestamp, truncated to sane sizes, with control characters stripped; no free-form queries from the caller)
- query_logs(service, env, since, level?, contains?, limit): builds LogQL from allow-listed parameters only.
- query_metric(name, service, env, window): `name` is an enum of parameterized PromQL templates (error_rate, p95_latency, request_rate, memory_vs_limit, volume_used_ratio, restart_count, ready_replicas, alert_state). No raw PromQL.
- get_pod_status(service, env): phase, ready, restartCount, lastState terminated reason and exit code, age.
- get_deployment_info(service, env): desired/available replicas, image, resources, env var names (values redacted), change-cause annotations, revision.
- get_rollout_history(service, env).
- get_recent_events(service, env, since).
- get_config(service, env): ConfigMap contents with secret-looking values redacted.
- get_config_history(service, env): list of snapshots (see 5).
- check_disk_usage(service, env): runs an allow-listed read-only command in the pod (df and a bounded listing of /data), returns used ratio and files with name, size, age, and a classification (archive | temp_dump | other).

3. Write tools
Required: restart_service, scale_deployment (bounded 1..6; scaling to 0 is not allowed), rollback_deploy (to previous or a named revision), restore_snapshot (kind configmap|deployment_spec, name, snapshot_id), cleanup_files (scope enum: temp_dumps | archive_older_than_days; never any other path), set_memory_limit (bounded range).
Every write tool must:
- use pydantic schemas with Literal allow-lists for service and env (no free text for targets),
- default dry_run=True, and return the planned diff in dry-run,
- check preconditions (target exists, snapshot is flagged healthy, values within bounds),
- be idempotent, with timeouts,
- return {ok, dry_run, planned_changes, applied_changes, pre_state_ref, error},
- write an audit row (tool_audit table in incident-db: ts, tool, args, caller, incident_id, result, duration),
- honor a global kill switch (a flag in incident-db or a ConfigMap): when on, all non-dry-run writes are refused,
- be rate limited (max N write calls per incident per minute).

4. Approval tokens (defense in depth)
- Non-dry-run write calls require an `approval_token`: an Ed25519-signed token binding {incident_id, tool, SHA-256 of args, env, expiry (max 10 minutes), nonce}. The gateway holds only the PUBLIC key (Secret) and enforces single-use nonces. The policy gate (Phase 5) will hold the private key. For now provide `tools/dev/issue_token.py` with a dev keypair for tests only, clearly marked as dev.
- Reject: missing, forged, expired, replayed, or args-mismatched tokens, with distinct error codes.

5. Config snapshotter
- A background task in the tool gateway captures ConfigMaps and deployment specs for web, api, db every 60 seconds into incident-db (config_snapshots: id, kind, name, env, content, content_hash, captured_at, healthy bool). Store only on change. `healthy` is true only if the service was ready with error rate below a threshold at capture time. Secret values are redacted before storage. restore_snapshot refuses snapshots not flagged healthy.

Tests
- Unit tests: schemas and allow-lists, bounds, token validation (all rejection cases), kill switch, rate limit, redaction, LogQL builder rejects injection attempts.
- Integration tests against the lab (tests may use the fault inject/reset scripts as fixtures): each read tool's output matches `kubectl` for the same thing. For each of the 5 faults, inject it, apply the corresponding write tool (dry-run first, then real with a dev token), and confirm recovery, then reset. Mapping to exercise: crash loop -> restore_snapshot(configmap)+restart; disk -> cleanup_files; service down -> scale_deployment; OOM -> restore_snapshot(deployment_spec); bad deploy -> rollback_deploy.
- Negative tests: cleanup_files cannot touch anything outside the two allowed scopes; scale to 0 refused; prod actions refused without a token; kill switch blocks everything.
- `make tools-test`; must pass twice.

Acceptance criteria
- RBAC evidence saved; every tool documented in tools/README.md (schema, risk, example).
- All tests pass; audit table shows every write call with args and result.
- `make up` deploys the gateway automatically and stays idempotent.

Milestones: M1 service skeleton + RBAC + auth; M2 read tools; M3 snapshotter; M4 token verification; M5 write tools; M6 integration tests; M7 docs.
Out of scope: the LLM agent, the policy service that issues tokens.
