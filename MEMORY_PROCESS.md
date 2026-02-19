# Memory Process Specification

- Version: 1.0
- Date: February 17, 2026
- Scope: Local API memory pipeline for Claude Code

## 1. Ingest Pipeline

1. Receive Claude Code hook event (`SessionStart`, `UserPromptSubmit`, `Stop`, `SessionEnd`, optional `PostToolUse`).
2. Normalize payload into `conversation`, `message`, and metadata fields.
3. Chunk text by conversational turn.
4. If chunk exceeds token limit, split with overlap.
5. Extract high-signal artifacts:
   - commands
   - errors
   - decisions
   - TODO commitments
6. Persist raw chunk and metadata.
7. Queue chunk for embedding generation.
8. Write embedding vector and mark chunk as retrievable.

## 2. Retrieval Pipeline

1. Receive query (`project_id`, `query`, optional `intent`, `k`, `token_budget`).
2. Run dense retrieval (vector top-K).
3. Run lexical retrieval (FTS5 BM25 top-K).
4. Fuse candidates using RRF.
5. Apply filters and boosts:
   - project scope filter
   - recency decay
   - chunk importance
   - intent/type match
6. Optionally rerank top-N with a reranker.
7. Deduplicate and package top results under token budget.
8. Return snippets + source metadata + diagnostics.

## 3. Memory Classes

1. Episodic:
   - session traces
   - high recency boost
2. Semantic:
   - stable project facts
   - high persistence
3. Procedural:
   - commands/runbooks
   - high operational relevance

## 4. Lifecycle and Retention

1. Keep raw chunks for hot window (default: 30 days).
2. Summarize low-value stale chunks into compact memories.
3. Keep durable facts/decisions until invalidated.
4. Run periodic compaction and index maintenance.

## 5. API Contracts (Minimum)

- `POST /v1/memory/ingest/message`
- `POST /v1/memory/ingest/messages/batch`
- `POST /v1/memory/ingest/chunks/embed`
- `POST /v1/memory/query`
- `POST /v1/memory/query/batch`
- `POST /v1/memory/facts/upsert`
- `POST /v1/memory/compact`
- `GET /v1/health`
- `GET /v1/admin/stats`
- `POST /v1/admin/reembed`
- `POST /v1/admin/checkpoint`
- `POST /v1/admin/vacuum`

## 6. Claude Code Hook Mapping

- `SessionStart` -> bootstrap memory brief
- `UserPromptSubmit` -> on-demand memory retrieval
- `Stop` / `SessionEnd` -> ingest and async embed
- `PostToolUse` (optional) -> capture command outcomes/errors

## 7. Quality Gates

1. p95 query latency < 150 ms.
2. Hybrid retrieval outperforms dense-only baseline on Recall@K.
3. Memory injection payload stays within configured token budget.
4. Secrets redaction passes before persistence.

## 8. Security Defaults

1. Bind service to localhost only.
2. Never persist explicit secrets or denied paths.
3. Keep audit logs for writes and retrieval injections.
4. Encrypt at rest if threat model requires it.
