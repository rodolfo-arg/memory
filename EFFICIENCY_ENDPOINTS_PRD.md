# PRD: Efficiency Endpoints for Memory Storage and Retrieval

- Version: 1.0
- Date: February 17, 2026
- Owner: Memory Platform
- Status: Implementation proposal

## 1. Purpose

Define a high-efficiency API surface for memory storage/retrieval that eliminates day-to-day raw SQL usage, improves throughput/latency, and reduces lock contention in local-first operation.

## 2. Problem

Current raw SQL operations are useful for debugging but inefficient and risky for normal workflows:

1. They bypass application safeguards (redaction, dedup, idempotency, audit).
2. They increase lock contention risk with ad-hoc write/read patterns.
3. They fragment observability (no consistent request-level metrics).
4. They make backend evolution harder (SQLite today, other engines later).

## 3. Product Goals

1. Replace routine SQL maintenance with explicit admin/ops endpoints.
2. Keep interactive retrieval under p95 150 ms (local baseline profile).
3. Keep ingestion ack under 1.5 s and retrieval hook overhead under 250 ms.
4. Provide batch APIs for high-throughput ingest/re-embed/backfill.
5. Preserve fail-open behavior for user-facing query paths.

## 4. Non-Goals

1. Remote multi-tenant authentication system in v1.
2. Web UI dashboard in v1.
3. Distributed cluster coordination.

## 5. Design Principles

1. API-first for normal operations; SQL reserved for emergency/debug only.
2. Idempotent writes by default using request IDs and deterministic hashes.
3. Short write transactions and staged commits to reduce DB lock duration.
4. Bounded payloads and explicit pagination/cursors.
5. Every endpoint emits metrics, timing, and structured error classes.

## 6. Endpoint Domains

## A) Ingestion Endpoints

### `POST /v1/memory/ingest/message`

Use:

- single message write path from hooks or integrations.

Efficiency requirements:

1. Return quickly after persistence + job enqueue.
2. No embedding inference inline.

### `POST /v1/memory/ingest/transcript`

Use:

- delta/full transcript ingestion.

Efficiency requirements:

1. Delta offset checkpointing per transcript path.
2. Chunk dedup using `chunk_hash`.
3. Batched DB inserts per transaction window.

### `POST /v1/memory/ingest/messages/batch` (new)

Use:

- high-throughput ingestion for imports/backfills.

Request:

```json
{
  "project_id": "memory",
  "conversation_id": "bulk-01",
  "messages": [
    {"role": "user", "content": "...", "created_at": "..."}
  ],
  "idempotency_key": "import-2026-02-17-01"
}
```

Response:

```json
{
  "accepted": true,
  "messages_ingested": 500,
  "chunks_created": 1420,
  "chunks_deduped": 80,
  "embedding_jobs_enqueued": 1340,
  "duration_ms": 412
}
```

## B) Retrieval Endpoints

### `POST /v1/memory/query`

Use:

- primary retrieval endpoint for prompt-time memory.

Efficiency requirements:

1. Dense + lexical candidate generation in bounded windows.
2. Fusion and packing with strict token budget.
3. Fail-open retrieval-log write behavior.

### `POST /v1/memory/query/batch` (new)

Use:

- prefetching context for multi-step agents or toolchains.

Request:

```json
{
  "project_id": "memory",
  "queries": [
    {"query": "latest migration command", "intent": "procedural", "k": 5, "token_budget": 800},
    {"query": "architecture decision for embeddings", "intent": "semantic", "k": 5, "token_budget": 800}
  ]
}
```

Response:

```json
{
  "results": [
    {"index": 0, "items": [], "diagnostics": {}},
    {"index": 1, "items": [], "diagnostics": {}}
  ],
  "duration_ms": 96
}
```

### `GET /v1/memory/bootstrap`

Use:

- fast session-start context summary.

Efficiency requirements:

1. no expensive reranking.
2. short candidate pool + token-capped output.

## C) Embedding/Queue Endpoints

### `POST /v1/memory/ingest/chunks/embed`

Use:

- explicit worker trigger and operational control.

Efficiency requirements:

1. Claim jobs atomically with status transition guard.
2. Commit after claim and per-job completion.
3. Backoff scheduling for retries.

### `POST /v1/admin/reembed` (new)

Use:

- re-embed selected scope after model change.

Request:

```json
{
  "project_id": "memory",
  "scope": "missing_or_model_mismatch",
  "target_model": "nomic-embed-text",
  "limit": 50000
}
```

Response:

```json
{
  "queued_jobs": 12480,
  "skipped_already_current": 880,
  "duration_ms": 325
}
```

## D) Maintenance Endpoints

### `POST /v1/memory/compact`

Use:

- summarize/archive low-value stale chunks.

Efficiency requirements:

1. bounded scan window.
2. chunk-level archive flag updates in batch.

### `POST /v1/admin/vacuum` (new)

Use:

- controlled maintenance window for DB compaction.

Constraints:

1. only run when queue depth below threshold.
2. returns maintenance state and elapsed time.

### `POST /v1/admin/checkpoint` (new)

Use:

- explicit WAL checkpoint control.

## E) Stats/Observability Endpoints

### `GET /v1/health`

### `GET /v1/metrics`

### `GET /v1/admin/stats` (new)

Return:

1. chunk counts by type/project.
2. queue depth by status.
3. embedding model distribution.
4. rolling p50/p95 timings for key endpoints.

## 7. Data/Transaction Efficiency Strategy

1. Keep transactions short and purpose-scoped.
2. Avoid holding write locks during network/model inference.
3. Apply `busy_timeout` and retry wrappers for non-critical writes.
4. Separate critical path from observability writes.
5. Prefer append/update-once patterns in logs and jobs.

## 8. Endpoint SLOs

1. `POST /v1/memory/query`:
   - p50 <= 60 ms
   - p95 <= 150 ms
2. `POST /v1/memory/ingest/message`:
   - p95 <= 80 ms
3. `POST /v1/memory/ingest/transcript` (delta <= 200 msgs):
   - p95 <= 1.5 s
4. `POST /v1/memory/ingest/messages/batch` (500 msgs):
   - p95 <= 800 ms (excluding model inference)

## 9. API Error Model

Use structured errors:

```json
{
  "error": {
    "code": "DB_LOCKED_RETRYABLE",
    "message": "database is locked",
    "retryable": true,
    "hint": "retry with backoff"
  }
}
```

Error classes:

1. `VALIDATION_ERROR`
2. `DB_LOCKED_RETRYABLE`
3. `EMBEDDING_PROVIDER_UNAVAILABLE`
4. `RATE_LIMITED_LOCAL`
5. `INTERNAL_ERROR`

## 10. Idempotency and Concurrency

1. Support `Idempotency-Key` header on batch writes.
2. Store idempotency ledger with TTL.
3. Use conditional updates for job claims.
4. Use fail-open semantics for non-critical side writes.

## 11. Security and Governance

1. Localhost bind only by default.
2. Admin endpoints can be optionally guarded by local token.
3. Redact secrets before persistence in all ingestion paths.
4. Keep transcript path denylist enforced in all ingest endpoints.

## 12. Proposed New Endpoint Set (Summary)

1. `POST /v1/memory/ingest/messages/batch`
2. `POST /v1/memory/query/batch`
3. `POST /v1/admin/reembed`
4. `GET /v1/admin/stats`
5. `POST /v1/admin/checkpoint`
6. `POST /v1/admin/vacuum`

## 13. Migration Plan from Raw SQL

## Phase 1: Endpoint parity (1-2 days)

1. Add missing admin APIs (`stats`, `checkpoint`, `reembed`).
2. Keep raw SQL scripts as fallback only.

Exit criteria:

- all current manual SQL maintenance tasks have endpoint equivalents.

## Phase 2: Batch performance (2-3 days)

1. Add `ingest/messages/batch` and `query/batch`.
2. Add load tests for batch and concurrency.

Exit criteria:

- batch endpoint SLOs met.

## Phase 3: Hardening (2-3 days)

1. Add idempotency ledger and retention.
2. Add structured error model and retry hints.
3. Extend metrics with per-endpoint p95.

Exit criteria:

- stable under lock-contention simulation and worker concurrency.

## Phase 4: Operational rollout (1-2 days)

1. Update runbooks to API-first operations.
2. Mark SQL scripts as emergency-only.

Exit criteria:

- no routine operator action requires direct SQL.

## 14. Test Strategy

1. Unit tests:
   - validation, error model, idempotency.
2. Integration tests:
   - ingest->embed->query loop under concurrency.
3. Load tests:
   - query p95, ingest bursts, mixed workload contention.
4. Failure drills:
   - embedding provider down, lock storms, partial worker outages.

## 15. Risks and Mitigations

1. Risk: endpoint explosion and maintenance overhead.
   - Mitigation: keep admin APIs minimal and capability-based.

2. Risk: batch endpoints increase lock pressure.
   - Mitigation: chunked commit windows and bounded batch sizes.

3. Risk: ops still bypass APIs out of habit.
   - Mitigation: runbook-first workflows and deprecate raw SQL docs.

## 16. Success Metrics

1. >= 95% of operational actions executed via API endpoints.
2. Query lock-related failures reduced to near-zero.
3. p95 retrieval and ingest SLOs maintained over 7-day rolling window.
4. Mean-time-to-recover for embedding/model migration cut by >= 50% using `/v1/admin/reembed`.

## 17. Implementation Notes for Current Repository

Given current codebase in `/Users/rodolfo/Developer/memory`:

1. Keep existing stable endpoints as-is.
2. Add new endpoints in `/Users/rodolfo/Developer/memory/app/main.py` and service handlers in `/Users/rodolfo/Developer/memory/app/service.py`.
3. Add idempotency ledger table in `/Users/rodolfo/Developer/memory/db/schema.sql`.
4. Extend load tooling in `/Users/rodolfo/Developer/memory/tests/load`.
5. Extend ops runbook in `/Users/rodolfo/Developer/memory/ops/RUNBOOK.md`.

## 18. Decision

Adopt API-first operations for memory storage/retrieval efficiency.

Raw SQL remains emergency-only, while all routine ingestion, retrieval, model migration, and maintenance flows move to explicit, observable, performance-bounded endpoints.
