# PRD: Local High-Performance Memory for Claude Code Conversations

- Version: 1.0
- Date: February 17, 2026
- Author: Codex
- Status: Draft for implementation

## 1. Executive Summary

This PRD defines a production-grade, local-first memory system for Claude Code that stores conversation history as structured chunks and retrieves relevant memory on demand through a local API.

The recommended architecture is:

- Ingestion and retrieval orchestration via Claude Code hooks (`UserPromptSubmit`, `SessionStart`, `Stop`, `SessionEnd`)
- Hybrid retrieval (dense vector + lexical BM25) with rank fusion
- Optional reranking stage for quality-sensitive queries
- SQLite-first storage for low operational overhead and high local performance
- Optional migration path to Qdrant or Postgres+pgvector when scale/complexity grows

This design optimizes for low latency, privacy (local only), and high relevance under coding workloads.

## 2. Problem Statement

Claude Code sessions generate high-value context (decisions, debugging trails, commands, architecture notes), but this context becomes hard to reuse unless memory is:

- Persisted across sessions
- Searchable by meaning and exact tokens
- Scoped by project/session/time
- Retrieved only when relevant (to avoid context pollution)

A naive vector-only approach is insufficient for code and tooling memory because exact terms (`TS-999`, command flags, file paths, API names) are often critical.

## 3. Goals and Non-Goals

### Goals

1. Persist conversation and session artifacts locally with zero cloud dependency.
2. Retrieve relevant memory in less than 150 ms p95 for common queries.
3. Support on-demand memory injection into Claude Code prompts.
4. Preserve precision for both semantic and exact-match queries.
5. Keep implementation maintainable with explicit schemas and lifecycle policies.

### Non-Goals

1. Building a distributed multi-tenant SaaS memory platform.
2. Replacing Claude Code built-in `CLAUDE.md` / auto-memory behavior.
3. Storing every token forever (must support summarization, compaction, and TTL).

## 4. Context From Current Claude Code Capabilities

As of February 17, 2026, Claude Code already provides:

- Auto memory and `CLAUDE.md`-based memory hierarchy
- `/memory` editing workflows
- Hooks at critical lifecycle points (including `UserPromptSubmit`, `SessionStart`, `Stop`, `SessionEnd`)
- Hook JSON output support to add context/decisions

Important implementation implications:

- Auto memory only loads the first 200 lines of `MEMORY.md` at session start.
- `CLAUDE.md` files are recursively discovered with scope precedence.
- Hooks can inject additional context or enforce control flow.

Therefore, this PRD proposes an external local memory service that complements, not replaces, Claude Code memory.

## 5. State-of-the-Art Retrieval Strategy (Recommended)

Use a multi-stage pipeline:

1. Hybrid candidate retrieval:
   - Dense retrieval for semantic similarity
   - Sparse/BM25 retrieval for exact terms and identifiers
2. Candidate fusion:
   - Reciprocal Rank Fusion (RRF) or DBSF
3. Optional reranking:
   - Cross-encoder or late-interaction model for top-N
4. Context packaging:
   - Deduplicate, diversify, and enforce token budget

Why this is current best practice:

- Anthropic Contextual Retrieval guidance shows strong gains from combining embeddings + BM25 + reranking.
- Qdrant and pgvector docs both explicitly support hybrid retrieval patterns.
- Pure dense retrieval misses exact keyword constraints in real code workflows.

## 6. Architecture Options

## Option A (Recommended v1): SQLite + `sqlite-vec` + FTS5 + Local Embedding Server

### Stack

- Metadata/event store: SQLite
- Vector search: `sqlite-vec` (`vec0` virtual tables)
- Lexical search: SQLite FTS5 (`bm25()` ranking)
- Embeddings API: local Ollama (`/api/embed`) or TEI
- API layer: local FastAPI/Node service (`localhost` only)

### Pros

- Minimal ops and dependencies
- Very fast local reads/writes for single-user workflows
- Easy backup and portability (single DB file)
- Strong exact-match + semantic search when hybridized

### Cons

- Fewer built-in advanced ANN features than specialized vector DBs
- Requires careful schema/index tuning as corpus grows

## Option B: Qdrant Local/Single-Node

### Stack

- Vector + payload engine: Qdrant
- Hybrid and multi-stage querying via Query API (`prefetch`, fusion)
- Quantization support for memory/speed tradeoffs
- Lexical data can be handled via sparse vectors or sidecar FTS index

### Pros

- Strong hybrid/retrieval ergonomics out of the box
- Better path to larger corpora and advanced ANN tuning
- Quantization and multistage search primitives are mature

### Cons

- Heavier runtime than SQLite-first
- Slightly higher operational complexity for local-only personal setup

## Option C: Postgres + pgvector + native text search

### Stack

- Postgres for relational + full text search + vectors (`pgvector`)

### Pros

- Unified SQL stack
- Strong transactional semantics and mature indexing
- Hybrid patterns documented directly in pgvector README

### Cons

- Heavier local footprint than SQLite
- More setup overhead for a single-user local memory agent

## Decision

- Start with Option A (SQLite-first) for fastest time-to-value and lowest operational burden.
- Keep adapters so migration to Option B or C is non-breaking when scale demands it.

## 7. Functional Requirements

1. Capture memory events from Claude Code lifecycle.
2. Store raw conversation units and derived chunks.
3. Generate embeddings asynchronously with retry/backoff.
4. Support hybrid retrieval and rerank.
5. Support metadata filters:
   - project
   - repo/worktree
   - session_id
   - timestamp range
   - memory type (episodic/semantic/procedural)
6. Return citations/snippets for explainability.
7. Provide CRUD and compaction endpoints.
8. Provide health and telemetry endpoints.

## 8. Non-Functional Requirements

1. Local-only networking by default (`127.0.0.1` / Unix socket).
2. p95 retrieval latency < 150 ms for <= 500k chunks.
3. Ingestion durability with crash-safe writes.
4. Deterministic schema migrations.
5. Configurable storage cap and retention policy.
6. Backups and restore procedures.

## 9. Data Model

## Core entities

- `conversation`
  - `conversation_id`
  - `project_id`
  - `started_at`, `ended_at`
  - `source` (`claude_code`)

- `message`
  - `message_id`
  - `conversation_id`
  - `role` (`user|assistant|tool|system`)
  - `content`
  - `created_at`
  - `token_count`

- `chunk`
  - `chunk_id`
  - `message_id`
  - `project_id`
  - `text`
  - `chunk_type` (`turn|summary|fact|decision|command|error`)
  - `start_char`, `end_char`
  - `created_at`
  - `importance_score`
  - `recency_bucket`
  - `contextual_prefix` (optional)

- `chunk_embedding`
  - `chunk_id`
  - `embedding_model`
  - `dim`
  - `vector`

- `memory_fact`
  - `fact_id`
  - `project_id`
  - `subject`, `predicate`, `object`
  - `confidence`
  - `last_verified_at`

- `retrieval_log`
  - `query_id`
  - `query_text`
  - `retrieved_chunk_ids`
  - `latency_ms`
  - `feedback_signal`

## Indexing

- FTS5 virtual table over chunk text and selected metadata text
- Vector table via `vec0` for ANN/KNN
- B-tree indexes on (`project_id`, `created_at`) and (`conversation_id`)

## 10. Chunking Strategy

Use hierarchical chunking tailored for conversational coding workflows:

1. Primary unit: semantic turn chunk
   - Keep user prompt + assistant answer boundaries intact
2. Secondary split for long turns
   - Target 300-800 tokens per chunk
   - 50-100 token overlap
3. Special chunk extractors
   - Commands
   - Errors/stack traces
   - Decisions and constraints
   - TODO commitments

### Contextualized chunking (recommended)

Before embedding, prepend 1-3 lines of concise context to each chunk:

- Project/repo identity
- File/module scope
- Time/session anchor
- Type marker (`decision`, `debugging`, `command`)

This follows the contextual retrieval pattern that improves recall in chunk-based RAG systems.

## 11. Embedding Strategy

## Default

- Local embedding service via Ollama `/api/embed`
- Keep one model for indexing and query embedding parity
- Use dimension control when model supports it to reduce footprint

## Model tiers

- Tier 1 (lightweight): local small embedding model for laptop CPU
- Tier 2 (balanced): stronger multilingual/local model for mixed workloads
- Tier 3 (high-quality): larger embedding models when GPU/RAM allow

## Optional accelerated serving

- Hugging Face TEI for high-throughput local inference and dynamic batching

## 12. Retrieval Pipeline Design

For each memory query:

1. Query understanding
   - Detect query intent (`fact`, `debug trace`, `command recall`, `decision recall`)
2. Candidate generation
   - Dense top-K (e.g., 60)
   - BM25 top-K (e.g., 60)
3. Fusion
   - RRF across dense + lexical sets
4. Filtering and boosts
   - Filter by `project_id`
   - Time-decay recency boost
   - Importance boost for explicit decisions/facts
5. Optional rerank
   - Rerank top 50 to top 10
6. Packing
   - Deduplicate semantically similar chunks
   - Enforce token budget and diversity

## Ranking formula (reference)

`final_score = w_rrf * rrf_score + w_recency * recency_decay + w_importance * importance + w_type * intent_type_match`

Weights are configurable per intent profile.

## 13. Local API Specification (v1)

## `POST /v1/memory/ingest/message`

- Purpose: ingest raw message and create chunks
- Request:
  - `project_id`
  - `conversation_id`
  - `message`
- Response:
  - `message_id`
  - `chunk_ids`

## `POST /v1/memory/ingest/chunks/embed`

- Purpose: embed pending chunks (sync or async)

## `POST /v1/memory/query`

- Purpose: retrieve memory for a user prompt
- Request:
  - `project_id`
  - `query`
  - `intent` (optional)
  - `k`
  - `token_budget`
- Response:
  - `results[]` with `chunk_id`, `score`, `snippet`, `source_meta`
  - `diagnostics` (latency, stage timings)

## `POST /v1/memory/facts/upsert`

- Purpose: persist distilled durable facts

## `POST /v1/memory/compact`

- Purpose: summarize stale low-value chunks and archive raw text

## `GET /v1/health`

- Purpose: liveness/readiness and model/index status

## 14. Claude Code Integration Plan

Integrate via `.claude/settings.local.json` hooks:

- `SessionStart`:
  - Call `GET /v1/memory/bootstrap?project_id=...`
  - Inject short memory briefing

- `UserPromptSubmit`:
  - Call `POST /v1/memory/query`
  - Return `additionalContext` with top chunks

- `Stop` or `SessionEnd`:
  - Send conversation delta for ingestion
  - Trigger async embedding + compaction jobs

- `PostToolUse` / `PostToolUseFailure` (optional advanced mode):
  - Capture concrete command outcomes and errors as high-signal memory

## 15. Memory Classes and Policies

Use three memory classes:

1. Episodic memory
   - Time-bound session traces
   - High recency weight
2. Semantic memory
   - Stable facts and architecture knowledge
   - High persistence
3. Procedural memory
   - Commands, workflows, runbooks
   - Retrieved often for operational prompts

Retention policy:

- Hot window: 30 days raw chunks
- Warm window: summarized/compacted chunks up to 180 days
- Durable facts/decisions: no TTL (until invalidated)

## 16. Performance and Capacity Targets

For single-user laptop baseline:

- Up to 1M chunks
- Embedding queue throughput: >= 200 chunks/minute on CPU baseline
- Query latency:
  - p50 < 60 ms
  - p95 < 150 ms
- Startup bootstrap memory load < 100 ms

## 17. Evaluation Plan

Offline evaluation set:

1. Build 200-500 real memory queries from historical sessions.
2. Label relevant chunks (gold set).
3. Track metrics:
   - Recall@K
   - MRR
   - nDCG@K
4. Compare pipelines:
   - Dense only
   - BM25 only
   - Hybrid
   - Hybrid + rerank

Online evaluation:

- Implicit signals:
  - retrieved chunk used in final answer
  - user correction frequency
  - repeated question rate
- Explicit signal:
  - quick thumbs up/down for memory hit usefulness

## 18. Security and Privacy Requirements

1. Bind service to localhost only.
2. Encrypt DB at rest if device threat model requires it.
3. Redact sensitive tokens before persistence (secrets, API keys).
4. Add hard denylist for paths/content classes that must never be stored.
5. Maintain audit log of memory writes and retrieval injections.

## 19. Observability and Operations

Collect per-stage telemetry:

- chunking latency
- embedding latency and queue depth
- retrieval stage timings
- rerank timings
- failure/error rates

Provide maintenance jobs:

- WAL checkpoint and vacuum scheduling
- stale chunk compaction
- index health verification

## 20. Rollout Plan

### Phase 0 (1-2 days): Skeleton

- API service scaffold
- SQLite schema + migrations
- Hook wiring with stub responses

### Phase 1 (3-5 days): Core retrieval

- Chunking + embedding pipeline
- Dense + BM25 retrieval
- RRF fusion
- Query endpoint usable in hooks

### Phase 2 (3-5 days): Quality

- Contextual chunk prefixes
- Optional reranker
- Evaluation harness + baseline metrics

### Phase 3 (2-4 days): Hardening

- Retention/compaction jobs
- security redaction
- observability dashboards/logs

## 21. Risks and Mitigations

1. Risk: Low relevance for exact technical tokens.
   - Mitigation: enforce lexical retrieval branch and hybrid fusion.

2. Risk: Retrieval latency spikes as corpus grows.
   - Mitigation: partition keys, recency filters, quantization (if Qdrant), compaction.

3. Risk: Memory pollution/noisy chunks.
   - Mitigation: chunk typing, importance thresholds, periodic summarization.

4. Risk: Prompt overloading from memory injection.
   - Mitigation: strict token budgets, diversity constraints, quote-first grounding pattern.

## 22. Recommended Build Choice

If the goal is "local, lightning fast, feasible now":

- Build Option A first (SQLite + `sqlite-vec` + FTS5 + Ollama/TEI)
- Keep clean interfaces so backend can switch to Qdrant later
- Add reranking only after hybrid baseline is stable and measured

This gives the best cost/complexity/performance tradeoff for a single-developer local memory system.

## 23. Appendix: Top-Level Process Markdown Template

Use this as the operational spec file (`MEMORY_PROCESS.md`) you mentioned:

```md
# Memory Process

## Ingest
1. Capture session/message events from Claude hooks.
2. Chunk by turn, then by token budget with overlap.
3. Extract high-signal artifacts (commands, errors, decisions).
4. Embed chunks with local embedding model.
5. Persist chunks + vectors + metadata.

## Retrieve
1. Receive query and infer intent.
2. Run dense + BM25 retrieval in parallel.
3. Fuse candidates and apply metadata/time filters.
4. (Optional) rerank top candidates.
5. Return top-k with citations/snippets.

## Maintain
1. Compact stale low-value chunks into summaries.
2. Keep durable facts and invalidate stale ones.
3. Monitor latency/quality metrics and tune thresholds.
```

## 24. References (Primary Sources)

1. Claude Code memory docs: https://code.claude.com/docs/en/memory
2. Claude Code hooks reference: https://code.claude.com/docs/en/hooks
3. Anthropic Contextual Retrieval (Sep 19, 2024): https://www.anthropic.com/engineering/contextual-retrieval
4. SQLite FTS5 docs (`bm25`, ranking): https://www.sqlite.org/fts5.html
5. SQLite WAL docs: https://sqlite.org/wal.html
6. `sqlite-vec` vec0 metadata/partition keys: https://alexgarcia.xyz/sqlite-vec/features/vec0.html
7. Qdrant hybrid queries and RRF/DBSF: https://qdrant.tech/documentation/concepts/hybrid-queries/
8. Qdrant quantization guide: https://qdrant.tech/documentation/guides/quantization/
9. pgvector README (HNSW/IVFFlat/hybrid guidance): https://github.com/pgvector/pgvector
10. Ollama embeddings capability docs: https://docs.ollama.com/capabilities/embeddings
11. Ollama `/api/embed` reference: https://docs.ollama.com/api/embed
12. Hugging Face Text Embeddings Inference (local serving): https://github.com/huggingface/text-embeddings-inference
13. BAAI BGE-M3 model card (dense+sparse+multi-vector): https://huggingface.co/BAAI/bge-m3
14. ColBERTv2 paper: https://arxiv.org/abs/2112.01488
