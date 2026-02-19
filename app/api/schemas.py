from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ApiErrorPayload(BaseModel):
    code: str
    message: str
    retryable: bool = False
    hint: str | None = None


class ErrorResponse(BaseModel):
    error: ApiErrorPayload


class IngestTranscriptRequest(BaseModel):
    project_id: str
    session_id: str
    transcript_path: str
    conversation_id: str | None = None
    ingest_mode: Literal["delta", "full"] = "delta"


class IngestMessageRequest(BaseModel):
    project_id: str
    conversation_id: str
    role: Literal["user", "assistant", "tool", "system"]
    content: str
    created_at: datetime | None = None


class IngestMessageItem(BaseModel):
    role: Literal["user", "assistant", "tool", "system"]
    content: str
    created_at: datetime | None = None


class IngestMessagesBatchRequest(BaseModel):
    project_id: str
    conversation_id: str
    messages: list[IngestMessageItem] = Field(min_length=1, max_length=5000)


class IngestResponse(BaseModel):
    accepted: bool = True
    messages_ingested: int
    chunks_created: int
    chunks_deduped: int
    embedding_jobs_enqueued: int


class IngestBatchResponse(IngestResponse):
    duration_ms: float
    idempotency_hit: bool = False


class EmbedRequest(BaseModel):
    batch_size: int = Field(default=64, ge=1, le=1000)


class EmbedResponse(BaseModel):
    processed_jobs: int
    completed_jobs: int
    failed_jobs: int


class QueryRequest(BaseModel):
    project_id: str
    query: str
    intent: str | None = "auto"
    k: int = Field(default=10, ge=1, le=50)
    token_budget: int = Field(default=1800, ge=200, le=10000)


class QueryBatchItem(BaseModel):
    query: str
    intent: str | None = "auto"
    k: int = Field(default=10, ge=1, le=50)
    token_budget: int = Field(default=1800, ge=200, le=10000)


class QueryBatchRequest(BaseModel):
    project_id: str
    queries: list[QueryBatchItem] = Field(min_length=1, max_length=100)


class QueryResultSource(BaseModel):
    conversation_id: str
    created_at: str
    chunk_type: str
    trust_level: str | None = None


class QueryResult(BaseModel):
    chunk_id: str
    score: float
    snippet: str
    source: QueryResultSource


class QueryDiagnostics(BaseModel):
    dense_ms: float
    bm25_ms: float
    fusion_ms: float
    rerank_ms: float
    total_ms: float


class QueryResponse(BaseModel):
    results: list[QueryResult]
    diagnostics: QueryDiagnostics


class QueryBatchResult(BaseModel):
    index: int
    items: list[QueryResult]
    diagnostics: QueryDiagnostics


class QueryBatchResponse(BaseModel):
    results: list[QueryBatchResult]
    duration_ms: float


class BootstrapResponse(BaseModel):
    context: str
    results: list[QueryResult]


class LatestMemoryItem(BaseModel):
    id: str
    kind: Literal["chunk", "fact"]
    created_at: str
    text: str
    conversation_id: str | None = None
    chunk_id: str | None = None
    fact_id: str | None = None
    chunk_type: str | None = None
    importance: float | None = None
    confidence: float | None = None
    trust_level: str | None = None


class LatestMemoryResponse(BaseModel):
    project_id: str
    items: list[LatestMemoryItem]


class ConversationSummaryItem(BaseModel):
    summary_text: str
    message_count: int
    summarizer_version: str | None = None
    updated_at: str


class ConversationMessageItem(BaseModel):
    message_id: str
    role: Literal["user", "assistant", "tool", "system"]
    created_at: str
    content: str
    raw_content: str | None = None


class ConversationMemoryResponse(BaseModel):
    project_id: str
    conversation_id: str
    started_at: str | None = None
    ended_at: str | None = None
    total_messages: int
    summary: ConversationSummaryItem | None = None
    messages: list[ConversationMessageItem]


class UpsertFactRequest(BaseModel):
    project_id: str
    fact_text: str
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    source_chunk_id: str | None = None


class UpsertFactResponse(BaseModel):
    fact_id: str
    status: str
    fact_chunk_id: str | None = None


class ChunkFeedbackRequest(BaseModel):
    chunk_id: str
    user_vote: float | None = Field(default=None, ge=-1.0, le=1.0)
    auto_judgement: float | None = Field(default=None, ge=-1.0, le=1.0)


class ChunkFeedbackResponse(BaseModel):
    chunk_id: str
    updated: bool


class CompactRequest(BaseModel):
    project_id: str
    max_chunks: int = Field(default=500, ge=10, le=5000)


class CompactResponse(BaseModel):
    scanned_chunks: int
    compacted_chunks: int
    summary_chunks_created: int


class AdminReembedRequest(BaseModel):
    project_id: str | None = None
    scope: Literal["missing_or_model_mismatch", "all"] = "missing_or_model_mismatch"
    target_model: str | None = None
    limit: int = Field(default=50000, ge=1, le=500000)


class AdminReembedResponse(BaseModel):
    queued_jobs: int
    skipped_already_current: int
    duration_ms: float


class AdminResummarizeRequest(BaseModel):
    project_id: str | None = None
    conversation_id: str | None = None
    limit: int = Field(default=5000, ge=1, le=50000)


class AdminResummarizeResponse(BaseModel):
    queued_jobs: int
    skipped_existing: int
    duration_ms: float


class EndpointLatencyStats(BaseModel):
    samples: int
    p50_ms: float
    p95_ms: float


class AdminStatsResponse(BaseModel):
    generated_at: str
    counts: dict[str, int]
    chunks_by_type: dict[str, int]
    jobs_by_status: dict[str, int]
    embeddings_by_model: dict[str, int]
    facts_by_status: dict[str, int]
    endpoint_latency_ms: dict[str, EndpointLatencyStats]


class AdminCheckpointRequest(BaseModel):
    mode: Literal["PASSIVE", "FULL", "RESTART", "TRUNCATE"] = "TRUNCATE"


class AdminCheckpointResponse(BaseModel):
    mode: str
    busy: int
    log_frames: int
    checkpointed_frames: int
    duration_ms: float


class AdminVacuumRequest(BaseModel):
    max_queued_jobs: int = Field(default=0, ge=0)
    analyze: bool = False


class AdminVacuumResponse(BaseModel):
    accepted: bool
    duration_ms: float
    details: dict[str, Any] = Field(default_factory=dict)


class MemoryGraphNodeData(BaseModel):
    id: str
    label: str
    kind: Literal["project", "conversation", "chunk", "fact"]
    text: str | None = None
    project_id: str | None = None
    conversation_id: str | None = None
    chunk_id: str | None = None
    fact_id: str | None = None
    chunk_type: str | None = None
    importance: float | None = None
    confidence: float | None = None
    archived: bool | None = None
    trust_level: str | None = None
    created_at: str | None = None


class MemoryGraphEdgeData(BaseModel):
    id: str
    source: str
    target: str
    kind: Literal["contains", "references"]


class MemoryGraphNode(BaseModel):
    data: MemoryGraphNodeData


class MemoryGraphEdge(BaseModel):
    data: MemoryGraphEdgeData


class MemoryGraphResponse(BaseModel):
    project_id: str
    nodes: list[MemoryGraphNode]
    edges: list[MemoryGraphEdge]
    totals: dict[str, int]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db_ok: bool
    embedding_provider_ok: bool
    pending_embedding_jobs: int
    details: dict[str, str] = Field(default_factory=dict)
