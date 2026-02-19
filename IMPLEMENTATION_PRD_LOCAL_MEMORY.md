# Implementation PRD: Production-Ready Local Memory System for Claude Code

- Version: 2.0
- Date: February 17, 2026
- Status: Implementation-ready
- Scope: Single-user, local-first memory platform with Claude Code hook integration

## 1) Executive Intent

Build a local memory application that continuously stores Claude Code conversation data as structured chunks and retrieves relevant context on demand with low latency and high precision.

This implementation plan takes the system from zero to production readiness, including:

- local API service
- ingestion + embedding + hybrid retrieval pipeline
- compaction and retention
- hook wiring and operational loop
- security, backup, and observability
- rollout and hardening

By the end of this plan, the repository has a `CLAUDE.md` contract and hook template that enforce the memory loop behavior (store/retrieve/maintain) at runtime.

## 2) Product Outcomes

### Primary outcomes

1. Memory survives across Claude Code sessions and worktrees.
2. Retrieval quality beats dense-only baseline on code tasks.
3. Query latency remains fast enough for interactive prompt workflows.
4. The system is reliable under crash/restart and recoverable from backups.

### Measurable success targets

1. `POST /v1/memory/query` p95 < 150 ms at 500k chunks (local laptop baseline).
2. Hybrid retrieval Recall@20 improves by >= 20% over dense-only baseline on internal eval set.
3. End-to-end hook time budget:
   - `UserPromptSubmit` budget: <= 250 ms extra wall-clock (including API call and formatting)
   - `SessionEnd` ingestion accepted within <= 1.5 s (async embedding allowed)
4. Memory write durability: zero confirmed data loss after controlled crash tests.

## 3) Non-Goals

1. Multi-tenant cloud service.
2. Remote synchronization in v1.
3. UI-heavy product in v1 (CLI + API + hook integration first).
4. Replacing Claude Code native memory features; this system complements them.

## 4) Research-Validated Constraints (as of February 17, 2026)

### Claude Code behavior constraints

1. Auto memory loads only first 200 lines of `MEMORY.md` at session start.
2. `UserPromptSubmit` hooks can inject `additionalContext` and can block prompts.
3. `SessionStart` and `SessionEnd` include session metadata and transcript path fields.
4. Hook input arrives on stdin as JSON; JSON output must be clean stdout on exit code 0.
5. `UserPromptSubmit` and `Stop` do not support `matcher` filtering and always fire.
6. Matching hooks run in parallel; duplicate handlers are deduplicated.

### Retrieval/storage constraints

1. Pure dense retrieval is insufficient for identifier-heavy code tasks; hybrid dense + lexical is preferred.
2. SQLite WAL improves concurrency and throughput but requires same-host file access and checkpoint hygiene.
3. SQLite FTS5 `bm25()`/`rank` supports lexical ranking and snippet generation.
4. `sqlite-vec` metadata filtering supports only specific operators and has partition-key over-sharding risk.
5. Qdrant hybrid Query API supports `prefetch` + `rrf`/`dbsf`; payload indexes are required for fast filtering.
6. pgvector ANN filtering happens after index scan; iterative scan options are critical for recall with filters.

### Embedding/rerank constraints

1. Ollama `/api/embed` supports batching and optional dimension control.
2. Ollama embed outputs are L2-normalized; consistent indexing/query model pairing is required.
3. TEI provides token-based dynamic batching and production telemetry for local accelerated serving.
4. Reranking improves quality but adds latency; must be optional and budgeted.

## 5) Product Requirements

### Functional requirements

1. Ingest session/transcript data.
2. Chunk conversational content with metadata.
3. Persist raw chunk text and embeddings.
4. Execute hybrid retrieval (dense + BM25) with fusion.
5. Optionally rerank top candidates.
6. Return explainable snippets/citations to Claude.
7. Classify and retain memory classes (episodic/semantic/procedural).
8. Compact old/noisy memory into summaries.
9. Expose health, metrics, and admin maintenance endpoints.

### Non-functional requirements

1. Local-only by default (`127.0.0.1` or unix socket).
2. Crash-safe writes and deterministic migrations.
3. Observability for latency/queue/errors.
4. Backup/restore runbook.
5. Secrets redaction before persistence.

## 6) Architecture Decision

## Recommended v1 stack (ship first)

- API/orchestration: FastAPI (Python 3.12)
- Primary store: SQLite
- Vector store: `sqlite-vec`
- Lexical search: SQLite FTS5
- Embeddings: Ollama local (`/api/embed`) default, TEI optional profile
- Queue: SQLite table-backed job queue (simple + durable)
- Hook integration: `.claude/settings.local.json` command hooks

## Why this stack

1. Lowest operational complexity for local single-user deployment.
2. Excellent real-world latency with SQLite + in-process API.
3. Clean migration path to Qdrant or pgvector when corpus growth or workload patterns demand it.
4. Python ecosystem simplifies transcript parsing, local ML integrations, and test tooling for this scope.

## Migration triggers

Move to Qdrant if:

1. chunk count exceeds 2M and recall-latency tuning in sqlite-vec plateaus,
2. heavy multi-vector workflows become default,
3. operational preference shifts toward dedicated vector runtime.

Move to Postgres + pgvector if:

1. existing app already standardizes on Postgres,
2. richer relational joins and SQL analytics are first-class requirements.

## 7) System Components

1. Hook Receiver Layer
   - Runs via Claude hooks as shell scripts.
   - Parses stdin JSON and calls local API.

2. Ingestion Service
   - Parses transcript deltas and message events.
   - Performs chunking and artifact extraction.

3. Embedding Worker
   - Pulls pending chunk jobs.
   - Calls embedding provider and stores vectors.

4. Retrieval Service
   - Runs dense and BM25 retrieval.
   - Fuses scores, filters, reranks, and packs output.

5. Compaction Service
   - Summarizes stale/noisy chunks.
   - Maintains durable facts and procedural memories.

6. Admin/Ops Service
   - Health, metrics, maintenance, snapshot/export/restore.

## 8) Canonical Data Model

## Core tables

- `conversations`
  - `conversation_id` TEXT PK
  - `project_id` TEXT NOT NULL
  - `session_id` TEXT NOT NULL
  - `transcript_path` TEXT
  - `started_at` DATETIME
  - `ended_at` DATETIME

- `messages`
  - `message_id` TEXT PK
  - `conversation_id` TEXT NOT NULL
  - `role` TEXT CHECK role in (`user`,`assistant`,`tool`,`system`)
  - `content` TEXT NOT NULL
  - `token_count` INTEGER
  - `created_at` DATETIME NOT NULL

- `chunks`
  - `chunk_id` TEXT PK
  - `message_id` TEXT
  - `project_id` TEXT NOT NULL
  - `conversation_id` TEXT NOT NULL
  - `chunk_text` TEXT NOT NULL
  - `chunk_type` TEXT
  - `importance` REAL DEFAULT 0.0
  - `created_at` DATETIME NOT NULL
  - `source_file` TEXT
  - `source_span` TEXT
  - `metadata_json` TEXT

- `chunk_embeddings`
  - `chunk_id` TEXT PK
  - `model` TEXT NOT NULL
  - `dimensions` INTEGER NOT NULL
  - `created_at` DATETIME NOT NULL

- `memory_facts`
  - `fact_id` TEXT PK
  - `project_id` TEXT NOT NULL
  - `fact_text` TEXT NOT NULL
  - `confidence` REAL NOT NULL
  - `source_chunk_id` TEXT
  - `status` TEXT CHECK status in (`active`,`stale`,`revoked`)
  - `updated_at` DATETIME NOT NULL

- `jobs`
  - `job_id` TEXT PK
  - `job_type` TEXT NOT NULL
  - `payload_json` TEXT NOT NULL
  - `status` TEXT CHECK status in (`queued`,`running`,`done`,`failed`)
  - `attempts` INTEGER DEFAULT 0
  - `run_after` DATETIME
  - `last_error` TEXT

- `retrieval_logs`
  - `query_id` TEXT PK
  - `project_id` TEXT NOT NULL
  - `query_text` TEXT NOT NULL
  - `intent` TEXT
  - `latency_ms` INTEGER
  - `result_chunk_ids_json` TEXT
  - `feedback` TEXT
  - `created_at` DATETIME NOT NULL

## Search indexes

1. FTS5 virtual table on chunk text + selected metadata text fields.
2. `sqlite-vec` `vec0` table for embeddings.
3. B-tree indexes:
   - (`project_id`, `created_at`)
   - (`conversation_id`)
   - (`job_type`, `status`, `run_after`)

## 9) Ingestion and Chunking Design

### Input sources

1. Hook event payloads with `transcript_path`.
2. Parsed transcript JSONL deltas.
3. Optional tool output events (`PostToolUse`, `PostToolUseFailure`).

### Chunking algorithm

1. Preserve turn boundaries first (user+assistant adjacency).
2. If a turn is too long, split into 300-800 token chunks with 50-100 token overlap.
3. Extract high-signal slices:
   - shell commands
   - stack traces/errors
   - decisions/constraints
   - TODO/commitments
4. Add contextual prefix before embedding:
   - `project_id`, session marker, memory class hint.

### Idempotency and de-dup

1. Compute deterministic `chunk_hash` (`sha256(project_id + normalized_text + source_ref)`).
2. Ignore inserts where hash already exists.
3. Hooks are parallelizable, so ingestion endpoint must be idempotent by design.

## 10) Retrieval Pipeline

### Stage A: Candidate generation

1. Dense top-K from vector search (default K=60).
2. BM25 top-K from FTS5 (default K=60).

### Stage B: Fusion

1. Use RRF by default.
2. Optionally support DBSF profile when backend is Qdrant.

### Stage C: Filtering and boosts

1. Mandatory project filter.
2. Optional time window and session filters.
3. Recency decay + importance boost + memory-class intent boost.

### Stage D: Optional rerank

1. Apply only to top 30-50 candidates.
2. Strict latency cap (e.g., 80 ms budget).
3. If timeout, fall back to fused rank.

### Stage E: Context packing

1. Deduplicate semantically similar chunks.
2. Enforce token budget.
3. Emit snippets with source metadata for traceability.

## 11) API Specification (Implementation Contract)

## `POST /v1/memory/ingest/transcript`

Purpose:

- Ingest transcript delta and enqueue embedding jobs.

Request:

```json
{
  "project_id": "memory",
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../abc123.jsonl",
  "conversation_id": "abc123",
  "ingest_mode": "delta"
}
```

Response:

```json
{
  "accepted": true,
  "messages_ingested": 14,
  "chunks_created": 37,
  "chunks_deduped": 5,
  "embedding_jobs_enqueued": 32
}
```

## `POST /v1/memory/query`

Purpose:

- Retrieve context chunks for an incoming user prompt.

Request:

```json
{
  "project_id": "memory",
  "query": "What command fixed the migration lock issue?",
  "intent": "procedural",
  "k": 10,
  "token_budget": 1800
}
```

Response:

```json
{
  "results": [
    {
      "chunk_id": "ch_01",
      "score": 0.812,
      "snippet": "Run `pnpm prisma migrate deploy` after clearing advisory lock...",
      "source": {
        "conversation_id": "abc123",
        "created_at": "2026-02-16T21:04:12Z",
        "chunk_type": "command"
      }
    }
  ],
  "diagnostics": {
    "dense_ms": 14,
    "bm25_ms": 9,
    "fusion_ms": 2,
    "rerank_ms": 0,
    "total_ms": 38
  }
}
```

## `POST /v1/memory/maintain/compact`

Purpose:

- Compact stale memory and promote durable facts.

## `GET /v1/health`

Purpose:

- Check db, vector index, embedding provider, queue backlog.

## `GET /v1/metrics`

Purpose:

- Prometheus/plain metrics endpoint.

## 12) Hook Integration Design

### Hook events used

1. `SessionStart`
   - fetch bootstrap memory summary and inject context.

2. `UserPromptSubmit`
   - call `/v1/memory/query`.
   - return `hookSpecificOutput.additionalContext`.

3. `PostToolUse` and `PostToolUseFailure` (optional in v1.1)
   - capture command outcomes and failures.

4. `SessionEnd`
   - call transcript ingest endpoint.

### Key guardrails from docs

1. `UserPromptSubmit` and `Stop` always fire; no matcher.
2. JSON output must be clean stdout on exit 0; avoid shell noise.
3. Hooks may run in parallel; API calls must be safe under concurrency.

## 13) Memory Class Policy

1. Episodic memory
   - short-lived session context.
   - recency boosted.

2. Semantic memory
   - stable facts about architecture or environment.
   - no default TTL, but revalidation workflow.

3. Procedural memory
   - reproducible commands and runbooks.
   - high priority for operational prompts.

## Retention defaults

1. Raw episodic chunks: 30 days.
2. Compacted summaries: 180 days.
3. Durable facts/procedures: indefinite until stale/revoked.

## 14) Security, Privacy, and Compliance

1. Bind API service to `127.0.0.1` only.
2. Secrets redaction pipeline before writes:
   - API keys
   - tokens
   - private cert blocks
3. Path denylist for sensitive files (e.g., `.env`, key stores).
4. Audit log for all memory writes and query injections.
5. Optional at-rest encryption profile for sensitive workstations.

## Qdrant-specific hardening (if adopted)

1. API key + TLS together.
2. Explicit network bind to loopback/private interface.
3. Restrict internal ports and outbound network where possible.

## 15) Observability Plan

### Metrics

1. Ingestion throughput (messages/chunks per minute).
2. Embedding queue depth + retry counts.
3. Query stage timings (dense/bm25/fusion/rerank/total).
4. Recall@K and user feedback signal.
5. Error rates by endpoint and hook event.

### Logs

1. Structured JSON logs with `request_id`, `session_id`, `project_id`.
2. Redact PII/secrets at sink.
3. Separate audit log channel for compliance-sensitive events.

## 16) Backup, Restore, and Disaster Recovery

### SQLite profile

1. Daily backup copy with WAL checkpoint and consistency verification.
2. Weekly restore drill into temp location.
3. Retain rolling 14 daily + 8 weekly backups.

### Qdrant profile (if adopted)

1. Collection snapshots on schedule.
2. Validate restore compatibility with minor version constraints.
3. Keep restore SOP in repo.

## 17) Performance Engineering Plan

1. Baseline benchmarks at 50k, 250k, 500k, 1M chunks.
2. Tune vector K, BM25 K, and fusion weights per intent.
3. Tune SQLite pragmas:
   - WAL mode
   - synchronous profile
   - checkpoint cadence
4. Add load tests for concurrent prompt submissions.
5. Add tail-latency budget for rerank stage; auto-disable on degradation.

## 18) Evaluation Framework

### Offline

1. Build labeled benchmark set from real prompts.
2. Evaluate:
   - Recall@K
   - MRR
   - nDCG
   - failure-rate@20
3. Compare:
   - dense-only
   - bm25-only
   - hybrid
   - hybrid + rerank

### Online

1. Track memory-useful vs memory-noise interactions.
2. Track repeated-question rate and correction frequency.
3. Add thumbs feedback endpoint for explicit signal.

## 19) Production Readiness Checklist

A release is blocked until all items pass.

### Reliability

1. Crash/restart tests pass.
2. Queue replay idempotency verified.
3. Hook failures fail open safely (user workflow not bricked).

### Quality

1. Hybrid >= target improvement vs dense-only.
2. No major regression in retrieval latency.

### Security

1. Local bind verified.
2. Redaction tests pass.
3. Audit log entries complete for write/query actions.

### Operations

1. Backup + restore validated.
2. Metrics and alert thresholds configured.

## 20) End-to-End Delivery Phases

## Phase 0: Foundation and Repo Scaffolding (2-3 days)

Deliverables:

1. Service skeleton (`app/`, `workers/`, `db/`, `hooks/`, `tests/`).
2. Config system (`.env.example`, runtime profiles).
3. Migration framework and initial schema.

Exit criteria:

1. Service starts locally.
2. Health endpoint reports db connectivity.

## Phase 1: Ingestion Core (3-5 days)

Deliverables:

1. Transcript parser.
2. Chunking pipeline.
3. Durable writes + dedup.

Exit criteria:

1. Transcript ingest endpoint stores messages/chunks correctly.
2. Idempotency tests green.

## Phase 2: Embedding Pipeline (2-4 days)

Deliverables:

1. Embedding queue worker.
2. Ollama provider adapter.
3. Retry/backoff and poison-job handling.

Exit criteria:

1. Chunks become searchable after embedding.
2. Worker can recover from provider failures.

## Phase 3: Hybrid Retrieval (3-5 days)

Deliverables:

1. Dense retrieval queries.
2. BM25 retrieval queries (FTS5).
3. Fusion and metadata filtering.
4. Query endpoint contract.

Exit criteria:

1. Query endpoint returns grounded snippets with diagnostics.
2. Hybrid beats dense-only on quick benchmark.

## Phase 4: Hook Loop Integration (2-4 days)

Deliverables:

1. Hook scripts:
   - `session_start.sh`
   - `user_prompt_submit.sh`
   - `session_end.sh`
2. `.claude/settings.local.json` wiring profile.
3. `CLAUDE.md` loop instructions.

Exit criteria:

1. Context injected on prompt submit.
2. Session end triggers ingest automatically.

## Phase 5: Memory Maintenance (3-4 days)

Deliverables:

1. Compaction job.
2. Fact extraction/upsert.
3. Retention enforcement.

Exit criteria:

1. Storage growth controlled.
2. Durable memory classes usable in retrieval.

## Phase 6: Rerank + Quality Tuning (3-5 days)

Deliverables:

1. Optional rerank stage.
2. Intent-specific ranking profiles.
3. Evaluation harness with report output.

Exit criteria:

1. Quality gains are measurable and latency remains within budget.

## Phase 7: Security and Operations Hardening (3-5 days)

Deliverables:

1. Redaction + denylist.
2. Audit logs.
3. Backup/restore jobs and runbook.
4. Metrics + dashboards.

Exit criteria:

1. Security checklist complete.
2. Restore drill succeeds.

## Phase 8: Production Readiness and Release (2-3 days)

Deliverables:

1. Release checklist signoff.
2. Versioned deployment package.
3. Post-release monitoring plan.

Exit criteria:

1. All production gates pass.
2. Rollback and support playbook validated.

## 21) Implementation File/Module Plan

```text
memory/
  IMPLEMENTATION_PRD_LOCAL_MEMORY.md
  CLAUDE.md
  MEMORY_PROCESS.md
  .claude/
    settings.local.json.example
  app/
    main.py
    api/
    domain/
    retrieval/
    ingestion/
    maintenance/
  workers/
    embedding_worker.py
    compaction_worker.py
  db/
    migrations/
    schema.sql
  hooks/
    session_start.sh
    user_prompt_submit.sh
    session_end.sh
  tests/
    unit/
    integration/
    load/
```

## 22) Known Risks and Mitigations

1. Hook JSON parse failure due to noisy shell startup output.
   - Mitigation: run hook scripts with minimal shell profiles and strict stdout discipline.

2. WAL file growth and checkpoint starvation under long readers.
   - Mitigation: checkpoint policy, background maintenance, query lifecycle hygiene.

3. Over-sharded `sqlite-vec` partition keys causing slow KNN.
   - Mitigation: enforce cardinality guardrails and partition audits.

4. Hybrid relevance drift with poor BM25 tokenizer assumptions.
   - Mitigation: domain-aware tokenization tests and weighted profile tuning.

5. Rerank latency spikes.
   - Mitigation: feature flag rerank and hard timeout fallback.

## 23) Decision Log

1. Choose SQLite-first for v1.
   - Rationale: simplest reliable local deployment.

2. Enforce hybrid retrieval from day one.
   - Rationale: code/CLI identifiers need lexical branch.

3. Keep rerank optional in phase 6.
   - Rationale: quality gain with explicit latency tradeoff.

4. Use hooks-based integration, not manual prompt-only memory retrieval.
   - Rationale: deterministic memory loop and lower user burden.

## 24) Required Final Artifacts for “Production Ready” Claim

The app is considered production ready only when all are present:

1. Running local API with ingestion/query/maintenance endpoints.
2. Hook config active and tested end-to-end.
3. `CLAUDE.md` memory loop policy in repo root.
4. Backup + restore tested.
5. Quality + latency gates passing.
6. Security checklist completed.

## 25) Primary References Used

1. Claude Code memory docs: https://code.claude.com/docs/en/memory
2. Claude Code hooks docs: https://code.claude.com/docs/en/hooks
3. Anthropic contextual retrieval: https://www.anthropic.com/research/contextual-retrieval
4. SQLite FTS5: https://www.sqlite.org/fts5.html
5. SQLite WAL: https://www.sqlite.org/wal.html
6. sqlite-vec vec0 docs: https://alexgarcia.xyz/sqlite-vec/features/vec0.html
7. Qdrant hybrid queries: https://qdrant.tech/documentation/concepts/hybrid-queries/
8. Qdrant indexing: https://qdrant.tech/documentation/concepts/indexing/
9. Qdrant security: https://qdrant.tech/documentation/guides/security/
10. Qdrant capacity planning: https://qdrant.tech/documentation/guides/capacity-planning/
11. Qdrant quantization: https://qdrant.tech/documentation/guides/quantization/
12. pgvector README: https://github.com/pgvector/pgvector
13. Ollama embeddings capability: https://docs.ollama.com/capabilities/embeddings
14. Ollama `/api/embed`: https://docs.ollama.com/api/embed
15. TEI repository: https://github.com/huggingface/text-embeddings-inference
16. ColBERTv2 paper: https://arxiv.org/abs/2112.01488
