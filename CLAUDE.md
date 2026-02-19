# Claude Code Local Memory Loop Contract

## Purpose

This repository uses a local memory API to persist and retrieve conversation memory across sessions.

## Local Memory API

- Base URL: `http://127.0.0.1:4815`
- Required health endpoint: `GET /v1/health`
- Required query endpoint: `POST /v1/memory/query`
- Required latest endpoint: `GET /v1/memory/latest`
- Required ingest endpoint: `POST /v1/memory/ingest/transcript`
- Efficiency endpoints:
  - `POST /v1/memory/ingest/messages/batch`
  - `POST /v1/memory/query/batch`
  - `GET /v1/admin/stats`
  - `POST /v1/admin/reembed`
  - `POST /v1/admin/checkpoint`
  - `POST /v1/admin/vacuum`

## Runtime Loop (Store/Retrieve/Maintain)

1. On `SessionStart`:
   - fetch bootstrap memory summary from local API.
   - inject only concise relevant context.

2. On `UserPromptSubmit`:
   - query local memory using current prompt.
   - inject top relevant chunks as additional context.
   - enforce token budget and relevance threshold.

3. On `SessionEnd`:
   - ingest transcript delta into local memory.
   - enqueue embedding/maintenance jobs asynchronously.

4. Maintenance:
   - compact stale low-value chunks.
   - preserve durable facts/procedural memories.
   - use admin endpoints instead of routine raw SQL operations.

## Data Quality Rules

1. Prioritize project-scoped retrieval.
2. Use hybrid retrieval (dense + lexical) for code/CLI precision.
3. Include source metadata/snippets in returned context.
4. Never inject ungrounded memory claims.
5. Facts upserted via `POST /v1/memory/facts/upsert` must be mirrored into queryable `fact` chunks.
6. Hyphenated user queries must be FTS-safe sanitized (no SQL column interpretation errors).

## Security Rules

1. Service must bind to localhost only.
2. Do not store secrets (API keys, private tokens, cert blocks).
3. Apply denylist for sensitive file classes (`.env`, key stores).
4. Keep audit logs for memory writes and retrieval injections.

## Failure Behavior

1. If memory API is unavailable, continue task execution without memory injection.
2. Log the failure event for later remediation.
3. Do not block user workflows due to memory subsystem outages.
4. Structured API errors must include `code`, `retryable`, and optional `hint`.

## Performance Budgets

1. Query path target: p95 < 150 ms.
2. Hook-added overhead target (`UserPromptSubmit`): <= 250 ms.
3. Session ingest acceptance: <= 1.5 s with async embedding allowed.

## Source of Truth

- Implementation plan: `/Users/rodolfo/Developer/memory/IMPLEMENTATION_PRD_LOCAL_MEMORY.md`
- Process spec: `/Users/rodolfo/Developer/memory/MEMORY_PROCESS.md`
