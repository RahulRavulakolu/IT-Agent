# Phase 6 prompt: Execution, verification and escalation

> How to use: make sure AGENTS.md is in the repo root, then paste everything
> below the line into your coding assistant.
> Gate before moving on: all 5 faults get fixed end to end, every failure path
> ends in a clean state or a handoff, and killing the agent mid-run never
> causes a double action.

---

Phase 6: Execute, verify, replan and escalate (closed loop). Follow AGENTS.md.
Prerequisite: Phase 5 accepted.

Goal: complete the autonomous loop safely: run approved actions through the tool gateway, verify recovery with deterministic code, retry within bounds, and always end in either `resolved` or a well-documented human handoff.

1. Incident lifecycle (event-gateway): states open -> investigating -> planned -> awaiting_approval -> executing -> verifying -> resolved | escalated. Add endpoints to move agent-driven states and append timeline events; transitions are validated.

2. Nodes (agent/)
- snapshot_pre_state: record pre-action state (replicas, image, config hash, resource limits, current error rate, alert state) in an `executions` table.
- execute: call the write tool with the approval token. Idempotency: a resumed run checks the executions table first and never re-executes an action that already succeeded or is in flight (use an execution key from incident_id + step). Handle tool errors and timeouts (bounded retries only for transient errors).
- verify (DETERMINISTIC code, not the LLM): run the plan's verification_checks plus independent baseline checks: the original alert has resolved in Prometheus; ready replicas == desired; 5xx rate below threshold; no pod restarts during the window. Require ALL checks to hold continuously for a stability window (default 180 s, poll every 15 s, configurable). Detect flapping (recovers then fails again) and a worse-than-before result. Maximum verification time 10 minutes.
- replan: if verification fails, go back to the planner with the failure evidence. At most 2 replans; every new plan passes the policy gate again, including its own approval if required.
- compensating rollback: if the state is worse than the pre-state, run the plan's compensating action (also through the policy gate and tokens), or escalate if it is not allowed.
- escalate: Notifier interface (log + webhook; Slack optional). Sends a structured handoff: incident, what was observed, hypotheses and confidence, actions tried and results, current system state, suggested next step. Sets incident status=escalated.
- resolved: set status=resolved with verified evidence attached.

3. Escalation triggers (all must be implemented): policy deny; approval rejected or timed out; execution error; verification failed after retries; budget or time exceeded; confidence too low or category unknown; kill switch on; unexpected exception in any node (a top-level handler guarantees escalate instead of a silent failure).

4. Resource/time safety: global run timeout per incident, max concurrent runs, and only one active run per service (no two runs acting on the same target).

Tests (`make e2e`)
- Happy path: for each of the 5 faults in staging: inject, incident created, investigate, plan, gate (auto or approve via CLI), execute, verify, resolved, and the system really recovered (check with the same recovery query the lab uses). Record per-stage timings and MTTR.
- Failure paths, each with an assertion on final state and handoff content:
  a. fix does not work (use a test-only forced plan: restart_service for the bad deployment) -> verification fails -> replan -> correct fix or escalation;
  b. tool gateway down during execute -> escalate;
  c. approval rejected -> replan once, then escalate if rejected again;
  d. approval timeout -> escalate;
  e. kill switch flipped mid-run -> no further writes, escalate;
  f. agent process killed mid-execution and restarted -> resumes, no double execution (verify via tool_audit);
  g. two simultaneous incidents on different services -> two independent runs, no interference.
- Run the full e2e twice in a row; both must pass.

Acceptance criteria
- All happy-path and failure-path tests pass twice. Timing table saved (detect, diagnose, plan, approve, execute, verify, total).
- tool_audit shows exactly the expected writes and nothing else.
- A reviewer can reconstruct any run from the incident timeline alone.
- docs/phase6-lifecycle.md has the state diagram (Mermaid) and the escalation handoff format.

Milestones: M1 lifecycle states; M2 execute + idempotency; M3 verify; M4 replan + compensating rollback; M5 escalate + notifier; M6 happy-path e2e; M7 failure-path e2e; M8 docs.
Out of scope: postmortems, learning, dashboard.
