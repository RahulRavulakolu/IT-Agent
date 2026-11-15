# Phase 2 prompt: RAG knowledge base

> How to use: make sure AGENTS.md is in the repo root, then paste everything
> below the line into your coding assistant.
> Gate before moving on: `make rag-eval` meets the test-split targets and
> ingestion is idempotent.

---

Phase 2: RAG knowledge base and hybrid retrieval. Follow AGENTS.md.
Prerequisite: Phases 0 and 1 accepted (tag phase-1 exists).

Goal: a retrieval service the agent will use to find runbooks, service docs and similar past incidents, with retrieval quality MEASURED before any agent depends on it.

1. Storage
- Use incident-db (switch its image to a pinned pgvector/pgvector pg16 tag if needed; keep data compatible). Create schema `rag` with: documents (id, type runbook|incident|service_doc, title, source, content_hash, metadata jsonb, created_at), chunks (id, document_id, text, metadata jsonb, embedding vector(384), tsv tsvector). Indexes: HNSW (cosine) on embedding, GIN on tsv. Use the 'simple' text-search config so tokens like ENOSPC, OOMKilled, CrashLoopBackOff, exit code 137 are preserved.
- Embeddings: local, no external API (fastembed with BAAI/bge-small-en-v1.5, pinned). Bake the model into the image so pods do not download at runtime.

2. Corpus (write these yourself; keep them realistic and varied)
- rag/corpus/runbooks/*.md: about 12 GENERIC operational runbooks, each with: symptoms, how to diagnose (which signals to check), safe fixes, UNSAFE or ineffective actions and why, verification steps. Cover: crash loops from bad configuration, disk or volume exhaustion, OOM kills and memory leaks, bad release / regression and rollback, deployment scaled to zero or dead service, database connectivity problems, high latency, node pressure, DNS failure, certificate expiry, queue backlog, cache stampede.
- rag/corpus/incidents/*.json: about 40 synthetic past incidents. Schema: id, title, service, symptoms, evidence (sample log lines and metric patterns), root_cause, root_cause_category (enum: config_error, disk_exhaustion, service_unavailable, memory_exhaustion, bad_release, dependency_failure, other), resolution_steps, outcome (success|failed), human_confirmed (bool), time_to_resolve_minutes, date. Include about 3 differently-worded variants for each of the first five categories (different services and phrasing), about 15 incidents of OTHER types as distractors, and about 5 incidents where the first fix FAILED (these teach what does not work).
- rag/corpus/docs/*.md: generic service documentation for web, api, db (dependencies, config keys, deploy process, where logs and metrics live).
- Hard rule: the corpus must NOT mention this lab's fault names, scripts, image tags (for example api:v2-bad) or meta.yaml content. It must read like a real company's knowledge base. Do not ingest incident-lab/docs/fault-catalog.md.

3. Ingestion (`make rag-ingest`)
- Chunk runbooks by procedure step or heading, prefixing each chunk with document title and section path. Incidents: one chunk per incident plus a symptom-only chunk. Attach metadata (type, service, category, outcome, human_confirmed).
- Idempotent via content_hash: a second run reports 0 changes; edited files are re-embedded; removed files are deleted.

4. Retrieval service (`rag/service`, FastAPI, Deployment in namespace monitoring, image loaded into kind)
- POST /search {query, k, filters{type, service, category, outcome}} returns chunks with id, document id, title, source, scores, and a short snippet.
- Pipeline: vector top-30 + keyword top-30 -> reciprocal rank fusion -> cross-encoder rerank (behind a flag if too heavy on CPU) -> top-k. Also expose the same logic as an importable Python function `retrieve()` for the agent.
- /healthz, /readyz (checks database), /metrics, structured JSON logs.
- Return an explicit low-confidence signal when the best score is below a threshold, so callers can tell "nothing relevant found".

5. Retrieval evaluation (`make rag-eval`)
- rag/eval/queries.yaml: 40 queries, written the way an agent would phrase them from observed evidence. Mix: symptom descriptions, raw error-string-only queries, vague paraphrases, and 5 negative queries with no relevant document. Each has expected document ids. Split into dev (tune on these) and test (never tune on these).
- Report recall@1, recall@3, recall@5 and MRR for four configs: vector-only, keyword-only, hybrid, hybrid+rerank, on dev and test separately. Negative queries: report false-positive rate under the low-confidence threshold.
- Targets on the TEST split: hybrid recall@3 >= 0.85, and hybrid must beat both single-method configs. If not met, diagnose (chunking, query phrasing, weights) and improve without tuning on test.
- Also report search latency p50/p95 on CPU.

6. Docs: rag/README.md (design, corpus conventions, how to add documents), and update the root README roadmap to this plan: 0 Lab, 1 Detection, 2 RAG, 3 Tools, 4 Investigation agent, 5 Planner + policy gate, 6 Execute + verify, 7 Postmortem + learning, 8 Evaluation + hardening + UI, 9 Rollout + demo.

Acceptance criteria
- `make up` still works; `make rag-ingest` run twice shows 0 changes the second time.
- `make rag-eval` prints the comparison table; test-split targets met; ablation shows hybrid > single methods.
- Service answers /search from inside the cluster; p95 latency under 1 second on CPU.
- Unit tests for chunking, idempotent ingestion and RRF; pass twice.
- Evidence and results saved in docs/evidence/phase2/.

Milestones: M1 pgvector + schema; M2 corpus; M3 ingestion; M4 retrieval service; M5 evaluation + tuning; M6 docs.
Out of scope: any LLM agent logic, tools, policy.
