# Phase 7 prompt: Postmortems and the learning loop

> How to use: make sure AGENTS.md is in the repo root, then paste everything
> below the line into your coding assistant.
> Gate before moving on: the repeat-incident test passes and the regression
> numbers show no drop.

---

Phase 7: Documentation (postmortem) and learning loop. Follow AGENTS.md.
Prerequisite: Phase 6 accepted.

Goal: every resolved or escalated incident gets a grounded postmortem, and verified knowledge flows back into RAG safely so future incidents benefit.

1. Postmortem generation
- A `document` node assembles a PostmortemInput purely from recorded data in incident-db: alerts, timeline events, investigation report, evidence items, plans, policy decisions, approvals, executions, verification results, escalation handoff, timestamps.
- Deterministic code computes: timeline (ordered from events), durations (time to detect, diagnose, approve, resolve), actions and outcomes, counts.
- The LLM writes only narrative sections from that input: summary, impact, root-cause explanation, what worked, what did not, follow-up suggestions (clearly labeled as suggestions). It may not add events, numbers or actions.
- Grounding check in code: every claim in the narrative cites existing event or evidence ids; stated numbers match the computed values; referenced actions exist in executions. On failure regenerate once, otherwise mark `ungrounded` and fall back to a template-only postmortem (no narrative).
- Store in `postmortems` (JSON + rendered Markdown). Provide `make postmortem INCIDENT=<id>`.

2. Ticketing: TicketSystem interface. Default adapter writes to a `tickets` table in the gateway (status, summary, link to the postmortem). Optional Jira adapter enabled only by env vars. Ticket is updated when the incident changes state.

3. Feedback API: POST /incidents/{id}/feedback {root_cause_correct: bool, fix_correct: bool, notes} plus CLI (`make feedback ...`). Stored with the reviewer and time.

4. Learning loop
- On resolution that PASSED verification, or on human review, convert the incident into a RAG incident record in the Phase 2 corpus schema with extra fields: source=agent_generated, human_confirmed (null|true|false), verification_passed, provenance (incident id, run id). Ingest it through the existing pipeline.
- Escalated or failed incidents are indexed as outcome=failed ("what did not work") only after human review or when the failure itself is well-documented.
- Retrieval weighting: human_confirmed=true records boosted; agent-generated and unconfirmed records weighted lower; rejected records penalized and never returned as a recommended fix. Document the weights and where they live in config.
- Memory-poisoning controls: sanitize text, never index from an unverified or ungrounded run, keep provenance, and provide `make rag-delete ID=...` plus a quarantine flag.

Tests
- Postmortem: grounding unit tests; a test where the narrative invents an action or a wrong number is rejected; template fallback works when the LLM is unavailable.
- Learning loop e2e: resolve fault A -> record appears in RAG with correct metadata -> reset and re-inject the same fault -> retrieval returns the new record in the top 3 and the investigation cites it. Report steps and time for run 1 versus run 2 (improvement is not required, but report it honestly).
- Regression: re-run `make rag-eval` and `make agent-eval` (smaller run, 3 per fault) to show the new records do not degrade quality. Show the numbers before and after.
- Poisoning test: submit feedback marking a wrong fix as correct, confirm it is flagged and that a human_confirmed=false decision demotes it.
- All suites pass twice.

Acceptance criteria
- Each of the 5 faults produces a readable, grounded postmortem with correct computed durations.
- The learning loop demonstrably retrieves a previous run's record; no regression in RAG/agent eval.
- Docs: docs/learning-loop.md (data flow diagram, weighting, poisoning controls).

Milestones: M1 PostmortemInput + computed fields; M2 narrative + grounding check; M3 tickets; M4 feedback; M5 record conversion + ingestion; M6 weighting + safeguards; M7 tests + regression; M8 docs.
Out of scope: dashboard UI, large-scale evaluation.
