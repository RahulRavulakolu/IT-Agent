# Phase 9 prompt: Staged autonomy rollout, demo and release

> How to use: make sure AGENTS.md is in the repo root, then paste everything
> below the line into your coding assistant.
> Gate before finishing: the fresh-clone run passes, the demo has been
> rehearsed twice, and you can answer "what if the agent is wrong?" using the
> safety case.

---

Phase 9: Staged autonomy rollout, demo, and release. Follow AGENTS.md.
Prerequisite: Phase 8 accepted.

Goal: show how this system would be adopted in the real world (shadow -> approval -> limited autonomy), make a reliable demo, and package the repo so a stranger can reproduce everything.

1. Autonomy modes (policy gate reads a config table; the dashboard and CLI can change it; every change is audited)
- shadow: investigate, plan and dry-run only; never execute, never request approval; record "would have done".
- approval: every write requires a human approval.
- limited: only actions the rules mark `auto` run; everything else needs approval or is denied.
- Tests prove each mode's behavior for all 7 faults (for example in shadow, tool_audit shows zero non-dry-run writes). Mode defaults to approval after a fresh install.
- `make shadow-report`: for shadow-mode runs, compare the agent's proposed action to the acceptable_remediations and unacceptable_actions in meta.yaml (eval/ may read it) and compute agreement rate. Include "promotion criteria" in docs/rollout-plan.md, for example: shadow agreement >= 90% and 0 unsafe proposals over N incidents before moving to approval; approval acceptance >= 90% and 0 reverted actions before limited.

2. Demo
- `make demo FAULT=<id> MODE=approval|limited`: verifies health, starts port-forwards and the dashboard, injects the fault, tails a readable terminal timeline (detected, investigating with evidence, plan, policy decision, approval prompt if needed, execute, verify, postmortem path), then resets. Must be safe to run repeatedly.
- `make demo-record` saves a complete run (events, evidence, decisions, timings) to demo/recordings/<id>.json and `make demo-replay` plays it back in the dashboard without the cluster or the LLM (backup plan if the live demo breaks).
- docs/demo-script.md: a narrated 5-minute script with timestamps, what to click, what to say at each step, and the Q&A cheat sheet (why not let the LLM act directly, how injection is handled, what happens if the agent is wrong, what you would do next). Rehearse it twice and record real timings in the doc.

3. Documentation set
- Root README rewritten: problem, architecture diagram (Mermaid), the 3-command quickstart, headline results from RESULTS.md with intervals, safety model in one screen, limitations, roadmap.
- docs/architecture.md (components, data flow, trust boundaries), docs/operations-runbook.md (kill switch, modes, rotating keys, adding a tool, a runbook, a fault, restoring from backup), docs/safety-case.md (each safety claim -> the test that proves it).
- CHANGELOG.md; license file (ask me which license); repo description and topics.

4. Release engineering
- `make bootstrap`: from a fresh clone on a clean WSL2 Ubuntu with Docker, install nothing silently but check prerequisites with clear messages, then bring up everything.
- Fresh-clone test: new clone in a new directory, `make down && make bootstrap && make e2e` passes. Record the evidence.
- Tag v1.0.0 only if every earlier phase's tests and the fresh-clone test pass.

Acceptance criteria
- Mode tests pass for all faults; shadow-report runs; rollout-plan lists measurable promotion criteria.
- Live demo completes for at least 3 different faults in both modes, twice; replay works offline.
- Fresh-clone test passes; README numbers match the latest RESULTS.md exactly (a script `scripts/check-readme-numbers.sh` verifies this).

Milestones: M1 modes + tests; M2 shadow report; M3 demo + replay; M4 docs set; M5 release engineering + fresh-clone test; M6 tag.
Out of scope: new capabilities; anything that changes the measured results (if you must, re-run eval and update the numbers).
