# Phase 5 prompt: Planner, policy gate and approvals

> How to use: make sure AGENTS.md is in the repo root, then paste everything
> below the line into your coding assistant.
> Gate before moving on: the gate blocks every adversarial case and the
> approval flow works in both directions (approve and reject).

---

Phase 5: Remediation planner, deterministic policy gate, and human approvals. Follow AGENTS.md.
Prerequisite: Phase 4 accepted.

Goal: turn a root-cause report into a ranked, validated remediation plan, and decide with deterministic code (not the LLM) whether each step may run automatically, needs a human, or is denied. Execution itself comes in Phase 6; this phase ends with an execution-ready, token-bearing, dry-run-verified plan.

1. Planner node (agent/)
- Input: RootCauseReport, evidence, retrieved runbook fixes. Output RemediationPlan: ranked options, each {action (a write tool name), args, rationale, expected_effect, verification_checks (named metric templates and thresholds), compensating_action, preconditions, llm_risk_estimate (advisory only, never used by the policy gate)}.
- Plans are validated against the tool gateway's real schemas. Unknown tools, unknown fields or out-of-range args -> rejected and one repair attempt, then escalate.
- For the top option, run the write tool in dry-run mode and attach the planned diff to the plan.
- Prompts versioned. Planner must prefer the least invasive fix and must not propose actions the runbooks list as ineffective for the diagnosed cause.

2. Policy gate (`policy/`, separate FastAPI service in monitoring, with its own Secret holding the Ed25519 PRIVATE key; the agent cannot read it)
- Declarative rules in policy/rules.yaml, evaluated by plain Python (no LLM). Decision: auto | approve | deny, with reason codes. Rules cover:
  per-action rules by environment and argument bounds (for example scale_deployment: auto in staging up to 6, approve in prod; rollback_deploy: prod needs approval; restart_service: auto in staging, approve in prod for the db; any action on the database: deny and escalate);
  an allowed-actions-per-category matrix (for example rollback_deploy only for bad_release; cleanup_files only for disk_exhaustion; restart_service not accepted as a fix for bad_release or config_error) so the "restart everything" failure mode is blocked structurally;
  minimum diagnosis confidence for auto (default 0.8) and a requirement that the top hypothesis is complete and not "unknown";
  limits: max actions per incident (3), cooldown on repeating the same action (10 min), blast radius (instances affected);
  incident-level conditions: kill switch on -> deny everything; autonomy mode (shadow|approval|limited, read from config; default approval).
- The gate recomputes everything it needs from the plan and the stored incident, and never trusts LLM-provided risk, env or labels.
- On auto or approved, issue an Ed25519 approval token bound to (incident_id, tool, SHA-256 of args, env, expiry <= 10 min, nonce). Verify it works with the Phase 3 tool gateway (public key only there).
- Every decision is stored (policy_decisions: inputs, rules matched, decision, reasons) and shown in the incident timeline.

3. Approvals
- approvals table (id, incident_id, plan, dry_run_diff, evidence summary, status pending|approved|rejected|expired, approver, decided_at, reason).
- Channels behind an interface: (a) HTTP API + CLI (`make approvals`, `make approve ID=...`, `make reject ID=... REASON=...`); (b) optional Slack (Socket Mode, Block Kit message with summary, evidence, diff, Approve/Reject buttons) enabled only if SLACK env vars exist.
- Graph integration: LangGraph interrupt waits for a decision; timeout (default 15 min) -> escalate; rejection with a reason is fed back to the planner exactly once (the new plan passes the gate again).
- The approver identity and time are recorded. A token is issued only after approval.

4. Graph ends at `execution_ready` (or `escalated` / `denied`). It does NOT call write tools without dry_run in this phase.

Tests
- policy/tests: table-driven unit tests, at least 40 cases covering every rule branch, including boundaries.
- Adversarial tests: malformed plan; args out of bounds; tool not in catalog; plan argument tries another namespace or env; forged, replayed, expired, and mismatched-args tokens against the live tool gateway; a plan produced after a prompt-injection string in evidence proposing something destructive (for example deleting a database) -> must be denied.
- Property test: for generated random plans, the gate never returns auto for prod actions or database actions.
- Integration: for each of the 5 faults run investigate -> plan -> gate. Expected, shown in a table: staging fixes decided auto or approve per the rules; the decision and token are recorded; the dry-run diff is attached.
- `make policy-test`; passes twice.

Acceptance criteria
- 0 disallowed actions get through in all adversarial and property tests.
- Approval flow works end to end through the CLI, including reject-with-reason, timeout and the replan-once path.
- policy/README.md documents the rules in plain language (a table a manager could read) plus how to change a rule safely.

Milestones: M1 planner + schema validation; M2 policy rules + engine + tests; M3 token issuing + tool gateway integration; M4 approvals + interrupt; M5 adversarial/property tests; M6 docs.
Out of scope: executing changes, verification.
