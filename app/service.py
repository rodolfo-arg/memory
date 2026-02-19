from __future__ import annotations

import hashlib
import json
import math
import os
import re
import socket
import sqlite3
import threading
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter, sleep
from uuid import uuid4

from app.api.schemas import (
    AdminCheckpointResponse,
    AdminReembedRequest,
    AdminReembedResponse,
    AdminResummarizeRequest,
    AdminResummarizeResponse,
    AdminStatsResponse,
    AdminVacuumRequest,
    AdminVacuumResponse,
    BootstrapResponse,
    ChunkFeedbackRequest,
    ChunkFeedbackResponse,
    CompactRequest,
    CompactResponse,
    ConversationMemoryResponse,
    ConversationMessageItem,
    ConversationSummaryItem,
    EmbedResponse,
    HealthResponse,
    IngestBatchResponse,
    IngestMessageRequest,
    IngestResponse,
    IngestMessagesBatchRequest,
    IngestTranscriptRequest,
    LatestMemoryItem,
    LatestMemoryResponse,
    MemoryGraphEdge,
    MemoryGraphEdgeData,
    MemoryGraphNode,
    MemoryGraphNodeData,
    MemoryGraphResponse,
    QueryDiagnostics,
    QueryBatchRequest,
    QueryBatchResponse,
    QueryBatchResult,
    QueryRequest,
    QueryResponse,
    EndpointLatencyStats,
    QueryResult,
    QueryResultSource,
    UpsertFactRequest,
    UpsertFactResponse,
)
from app.config import Settings
from app.db import connect, run_migrations, transaction
from app.domain.embeddings import (
    EmbeddingError,
    EmbeddingProvider,
    MockEmbeddingProvider,
    OpenAICompatEmbeddingProvider,
    OllamaEmbeddingProvider,
    TEIEmbeddingProvider,
    cosine_similarity,
)
from app.domain.metrics import MetricsStore
from app.domain.redaction import redact_text
from app.domain.vector_index import QdrantVectorIndex, VectorIndexError
from app.errors import ApiError
from app.ingestion.chunker import extract_high_signal_chunks, split_turn_text
from app.ingestion.transcript import ParsedMessage, parse_transcript_delta
from app.maintenance.compaction import summarize_chunks
from app.retrieval.hybrid import (
    RankedCandidate,
    rrf_fuse_with_debug,
    to_fts_query,
    trim_to_token_budget,
)


class MemoryService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db_path = settings.db_path
        migrations_path = Path(__file__).resolve().parents[1] / "db" / "migrations"
        init_conn = connect(self.db_path)
        try:
            run_migrations(init_conn, migrations_path)
        finally:
            init_conn.close()
        self._local = threading.local()
        self.lock = _SessionGuard(self)
        self.worker_id = settings.memory_worker_id.strip() or f"{socket.gethostname()}:{os.getpid()}"
        self.embedding_provider = self._build_embedding_provider()
        self.retrieval_backend = settings.memory_retrieval_backend.strip().lower()
        if self.retrieval_backend not in {"sqlite", "qdrant"}:
            self.retrieval_backend = "sqlite"
        self.vector_index_error: str | None = None
        self.vector_index = self._build_vector_index()
        self._bootstrap_fact_chunks_with_retry()
        self._bootstrap_conversation_summaries_with_retry()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
            self._local.metrics = None
            self._local.depth = 0

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            raise RuntimeError("no active database connection")
        return conn

    @property
    def metrics(self) -> MetricsStore:
        metrics = getattr(self._local, "metrics", None)
        if metrics is None:
            metrics = MetricsStore(self.conn)
            self._local.metrics = metrics
        return metrics

    def _session_enter(self) -> None:
        depth = int(getattr(self._local, "depth", 0))
        if depth == 0:
            conn = connect(self.db_path)
            self._local.conn = conn
            self._local.metrics = MetricsStore(conn)
        self._local.depth = depth + 1

    def _session_exit(self) -> None:
        depth = int(getattr(self._local, "depth", 0))
        if depth <= 1:
            conn = getattr(self._local, "conn", None)
            if conn is not None:
                conn.close()
            self._local.conn = None
            self._local.metrics = None
            self._local.depth = 0
            return
        self._local.depth = depth - 1

    def record_endpoint_latency(self, endpoint: str, latency_ms: float) -> None:
        if latency_ms < 0:
            return

        now = _utc_iso()
        cutoff = (datetime.now(UTC) - timedelta(days=self.settings.memory_endpoint_latency_retention_days)).isoformat(
            timespec="seconds"
        )
        max_samples = self.settings.memory_endpoint_latency_max_samples_per_endpoint

        with self.lock:
            self.conn.execute(
                """
                INSERT INTO endpoint_latencies(endpoint, latency_ms, created_at)
                VALUES (?, ?, ?)
                """,
                (endpoint, latency_ms, now),
            )
            self.conn.execute(
                "DELETE FROM endpoint_latencies WHERE created_at < ?",
                (cutoff,),
            )
            self.conn.execute(
                """
                DELETE FROM endpoint_latencies
                WHERE endpoint = ?
                  AND id NOT IN (
                    SELECT id FROM endpoint_latencies
                    WHERE endpoint = ?
                    ORDER BY id DESC
                    LIMIT ?
                  )
                """,
                (endpoint, endpoint, max_samples),
            )
            self.conn.commit()

    def ingest_transcript(self, req: IngestTranscriptRequest) -> IngestResponse:
        messages_ingested = 0
        chunks_created = 0
        chunks_deduped = 0
        embedding_jobs_enqueued = 0

        if self._is_denied_transcript_path(req.transcript_path):
            with self.lock, transaction(self.conn):
                self.metrics.inc("ingest_transcript_denied")
            return IngestResponse(
                accepted=False,
                messages_ingested=0,
                chunks_created=0,
                chunks_deduped=0,
                embedding_jobs_enqueued=0,
            )

        conversation_id = req.conversation_id or req.session_id
        now = _utc_iso()
        source_mtime = _path_mtime_iso(req.transcript_path)

        with self.lock, transaction(self.conn):
            self._upsert_conversation(
                conversation_id=conversation_id,
                project_id=req.project_id,
                session_id=req.session_id,
                transcript_path=req.transcript_path,
                started_at=now,
            )

            last_line = 0
            if req.ingest_mode == "delta":
                row = self.conn.execute(
                    "SELECT last_line FROM ingest_offsets WHERE transcript_path = ?",
                    (req.transcript_path,),
                ).fetchone()
                if row:
                    last_line = int(row["last_line"])

            parsed_messages, total_lines = parse_transcript_delta(req.transcript_path, last_line)

            for parsed in parsed_messages:
                msg_id, created_count, dedup_count, enqueued = self._store_message_chunks(
                    project_id=req.project_id,
                    conversation_id=conversation_id,
                    parsed=parsed,
                    source_path=req.transcript_path,
                    source_mtime=source_mtime,
                )
                if msg_id:
                    messages_ingested += 1
                chunks_created += created_count
                chunks_deduped += dedup_count
                embedding_jobs_enqueued += enqueued

            if messages_ingested > 0:
                self._refresh_conversation_summary(
                    conversation_id=conversation_id,
                    project_id=req.project_id,
                )

            self.conn.execute(
                """
                INSERT INTO ingest_offsets(transcript_path, last_line, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(transcript_path)
                DO UPDATE SET last_line = excluded.last_line, updated_at = excluded.updated_at
                """,
                (req.transcript_path, total_lines, now),
            )

            self.metrics.inc("ingest_transcript_calls")
            self.metrics.inc("messages_ingested", messages_ingested)
            self.metrics.inc("chunks_created", chunks_created)
            self.metrics.inc("chunks_deduped", chunks_deduped)
            self.metrics.inc("embedding_jobs_enqueued", embedding_jobs_enqueued)

        return IngestResponse(
            accepted=True,
            messages_ingested=messages_ingested,
            chunks_created=chunks_created,
            chunks_deduped=chunks_deduped,
            embedding_jobs_enqueued=embedding_jobs_enqueued,
        )

    def ingest_message(self, req: IngestMessageRequest) -> IngestResponse:
        parsed = ParsedMessage(
            role=req.role,
            content=req.content,
            created_at=(req.created_at.isoformat() if req.created_at else _utc_iso()),
        )
        chunks_created = 0
        chunks_deduped = 0
        embedding_jobs_enqueued = 0

        with self.lock, transaction(self.conn):
            self._upsert_conversation(
                conversation_id=req.conversation_id,
                project_id=req.project_id,
                session_id=req.conversation_id,
                transcript_path="",
                started_at=_utc_iso(),
            )
            msg_id, created_count, dedup_count, enqueued = self._store_message_chunks(
                project_id=req.project_id,
                conversation_id=req.conversation_id,
                parsed=parsed,
                source_path=f"conversation:{req.conversation_id}",
            )
            _ = msg_id
            self._refresh_conversation_summary(
                conversation_id=req.conversation_id,
                project_id=req.project_id,
            )
            chunks_created += created_count
            chunks_deduped += dedup_count
            embedding_jobs_enqueued += enqueued
            self.metrics.inc("ingest_message_calls")

        return IngestResponse(
            accepted=True,
            messages_ingested=1,
            chunks_created=chunks_created,
            chunks_deduped=chunks_deduped,
            embedding_jobs_enqueued=embedding_jobs_enqueued,
        )

    def ingest_messages_batch(
        self, req: IngestMessagesBatchRequest, idempotency_key: str | None = None
    ) -> IngestBatchResponse:
        started = perf_counter()
        if len(req.messages) > self.settings.memory_ingest_batch_max_messages:
            raise ApiError(
                code="VALIDATION_ERROR",
                message=(
                    f"batch size {len(req.messages)} exceeds max "
                    f"{self.settings.memory_ingest_batch_max_messages}"
                ),
                status_code=422,
                retryable=False,
                hint="reduce batch size",
            )

        req_payload = req.model_dump(mode="json")
        req_hash = _request_hash(req_payload)
        idempotent_hit = False

        with self.lock:
            if idempotency_key:
                cached = self._get_idempotent_response(
                    endpoint="/v1/memory/ingest/messages/batch",
                    idempotency_key=idempotency_key,
                    request_hash=req_hash,
                )
                if cached is not None:
                    idempotent_hit = True
                    return IngestBatchResponse(**cached, idempotency_hit=True)

        messages_ingested = 0
        chunks_created = 0
        chunks_deduped = 0
        embedding_jobs_enqueued = 0
        now = _utc_iso()

        with self.lock, transaction(self.conn):
            self._upsert_conversation(
                conversation_id=req.conversation_id,
                project_id=req.project_id,
                session_id=req.conversation_id,
                transcript_path="",
                started_at=now,
            )
            for item in req.messages:
                parsed = ParsedMessage(
                    role=item.role,
                    content=item.content,
                    created_at=(item.created_at.isoformat() if item.created_at else now),
                )
                msg_id, created_count, dedup_count, enqueued = self._store_message_chunks(
                    project_id=req.project_id,
                    conversation_id=req.conversation_id,
                    parsed=parsed,
                    source_path=f"conversation:{req.conversation_id}",
                )
                if msg_id:
                    messages_ingested += 1
                chunks_created += created_count
                chunks_deduped += dedup_count
                embedding_jobs_enqueued += enqueued

            if messages_ingested > 0:
                self._refresh_conversation_summary(
                    conversation_id=req.conversation_id,
                    project_id=req.project_id,
                )

            self.metrics.inc("ingest_batch_calls")
            self.metrics.inc("messages_ingested", messages_ingested)
            self.metrics.inc("chunks_created", chunks_created)
            self.metrics.inc("chunks_deduped", chunks_deduped)
            self.metrics.inc("embedding_jobs_enqueued", embedding_jobs_enqueued)

            result_payload = {
                "accepted": True,
                "messages_ingested": messages_ingested,
                "chunks_created": chunks_created,
                "chunks_deduped": chunks_deduped,
                "embedding_jobs_enqueued": embedding_jobs_enqueued,
                "duration_ms": _ms(perf_counter() - started),
            }

            if idempotency_key:
                self._save_idempotent_response(
                    endpoint="/v1/memory/ingest/messages/batch",
                    idempotency_key=idempotency_key,
                    request_hash=req_hash,
                    response_payload=result_payload,
                    status_code=200,
                )

        return IngestBatchResponse(**result_payload, idempotency_hit=idempotent_hit)

    def embed_pending(self, batch_size: int) -> EmbedResponse:
        processed = 0
        completed = 0
        failed = 0

        with self.lock:
            rows = self._claim_embed_jobs(batch_size=batch_size)

            if not rows:
                return EmbedResponse(processed_jobs=0, completed_jobs=0, failed_jobs=0)

            for row in rows:
                processed += 1
                job_id = row["job_id"]
                attempts = int(row["attempts"])

                try:
                    payload = json.loads(row["payload_json"])
                    chunk_id = payload["chunk_id"]
                    chunk_row = self.conn.execute(
                        """
                        SELECT
                          chunk_text,
                          project_id,
                          conversation_id,
                          chunk_type,
                          created_at,
                          importance,
                          trust_level,
                          archived
                        FROM chunks
                        WHERE chunk_id = ?
                        """,
                        (chunk_id,),
                    ).fetchone()
                    if not chunk_row:
                        raise EmbeddingError(f"chunk not found: {chunk_id}")

                    vector = self.embedding_provider.embed([chunk_row["chunk_text"]])[0]
                    self.conn.execute(
                        """
                        INSERT INTO chunk_embeddings(
                          chunk_id, model, dimensions, embed_model_id, dim,
                          embed_model, embed_dim, distance_metric, vector_json, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(chunk_id)
                        DO UPDATE SET
                          model=excluded.model,
                          dimensions=excluded.dimensions,
                          embed_model_id=excluded.embed_model_id,
                          dim=excluded.dim,
                          embed_model=excluded.embed_model,
                          embed_dim=excluded.embed_dim,
                          distance_metric=excluded.distance_metric,
                          vector_json=excluded.vector_json,
                          created_at=excluded.created_at
                        """,
                        (
                            chunk_id,
                            self.embedding_provider.model,
                            len(vector),
                            self.embedding_provider.model,
                            len(vector),
                            self.embedding_provider.model,
                            len(vector),
                            self.settings.memory_embed_distance_metric,
                            json.dumps(vector),
                            _utc_iso(),
                        ),
                    )
                    if self.vector_index is not None:
                        self._upsert_qdrant_point(
                            chunk_id=chunk_id,
                            vector=vector,
                            chunk_row=chunk_row,
                        )
                    self.conn.execute(
                        """
                        UPDATE jobs
                        SET status='done',
                            lease_until=NULL,
                            leased_by=NULL,
                            updated_at=?,
                            last_error=NULL
                        WHERE job_id=?
                        """,
                        (_utc_iso(), job_id),
                    )
                    self.conn.commit()
                    completed += 1

                except Exception as exc:  # noqa: BLE001
                    next_attempts = attempts + 1
                    if next_attempts >= 5:
                        status = "failed"
                        run_after = None
                    else:
                        status = "pending"
                        backoff = min(300, 2**next_attempts)
                        run_after = (datetime.now(UTC) + timedelta(seconds=backoff)).isoformat(
                            timespec="seconds"
                        )
                    self.conn.execute(
                        """
                        UPDATE jobs
                        SET status=?,
                            attempts=?,
                            run_after=?,
                            lease_until=NULL,
                            leased_by=NULL,
                            last_error=?,
                            updated_at=?
                        WHERE job_id=?
                        """,
                        (status, next_attempts, run_after, str(exc)[:500], _utc_iso(), job_id),
                    )
                    self.conn.commit()
                    failed += 1

            self.metrics.inc("embed_worker_runs")
            self.metrics.inc("embed_jobs_processed", processed)
            self.metrics.inc("embed_jobs_completed", completed)
            self.metrics.inc("embed_jobs_failed", failed)
            self.conn.commit()

        return EmbedResponse(processed_jobs=processed, completed_jobs=completed, failed_jobs=failed)

    def _claim_embed_jobs(self, *, batch_size: int) -> list[sqlite3.Row]:
        now = _utc_iso()
        lease_seconds = max(15, int(self.settings.memory_embed_job_lease_seconds))
        lease_until = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            # Recover stale running jobs if the previous worker crashed mid-flight.
            self.conn.execute(
                """
                UPDATE jobs
                SET status='pending', lease_until=NULL, leased_by=NULL, updated_at=?
                WHERE job_type='embed_chunk'
                  AND status='running'
                  AND lease_until IS NOT NULL
                  AND lease_until < ?
                """,
                (now, now),
            )

            # Backward-compatible cleanup for older rows before 0004 migration.
            self.conn.execute(
                """
                UPDATE jobs
                SET status='pending', lease_until=NULL, leased_by=NULL, updated_at=?
                WHERE job_type='embed_chunk'
                  AND status='queued'
                """,
                (now,),
            )

            rows = self.conn.execute(
                """
                SELECT job_id, payload_json, attempts
                FROM jobs
                WHERE job_type = 'embed_chunk'
                  AND status = 'pending'
                  AND (run_after IS NULL OR run_after <= ?)
                  AND (lease_until IS NULL OR lease_until < ?)
                ORDER BY created_at
                LIMIT ?
                """,
                (now, now, batch_size),
            ).fetchall()
            if not rows:
                self.conn.commit()
                return []

            job_ids = [str(row["job_id"]) for row in rows]
            placeholders = ",".join("?" for _ in job_ids)
            self.conn.execute(
                f"""
                UPDATE jobs
                SET status='running',
                    lease_until=?,
                    leased_by=?,
                    updated_at=?
                WHERE status='pending'
                  AND (lease_until IS NULL OR lease_until < ?)
                  AND job_id IN ({placeholders})
                """,
                (lease_until, self.worker_id, now, now, *job_ids),
            )
            self.conn.commit()
            return rows
        except Exception:
            self.conn.rollback()
            raise

    def _upsert_qdrant_point(
        self,
        *,
        chunk_id: str,
        vector: list[float],
        chunk_row: sqlite3.Row,
    ) -> None:
        if self.vector_index is None:
            return

        point = {
            "id": chunk_id,
            "vector": vector,
            "payload": {
                "chunk_id": chunk_id,
                "project_id": str(chunk_row["project_id"]),
                "conversation_id": str(chunk_row["conversation_id"]),
                "chunk_type": str(chunk_row["chunk_type"]),
                "created_at": str(chunk_row["created_at"]),
                "importance": float(chunk_row["importance"]),
                "trust_level": str(chunk_row["trust_level"] or "untrusted"),
                "archived": int(chunk_row["archived"]),
            },
        }
        try:
            self.vector_index.upsert_points([point])
            self.metrics.inc("qdrant_upserts")
        except Exception as exc:  # noqa: BLE001
            self.metrics.inc("qdrant_upsert_errors")
            self.vector_index_error = str(exc)

    def query_memory(self, req: QueryRequest) -> QueryResponse:
        with self.lock:
            return self._query_memory_locked(req, write_log=True)

    def query_memory_batch(self, req: QueryBatchRequest) -> QueryBatchResponse:
        started = perf_counter()
        results: list[QueryBatchResult] = []
        with self.lock:
            for idx, item in enumerate(req.queries):
                single = QueryRequest(
                    project_id=req.project_id,
                    query=item.query,
                    intent=item.intent,
                    k=item.k,
                    token_budget=item.token_budget,
                )
                response = self._query_memory_locked(single, write_log=False)
                results.append(
                    QueryBatchResult(index=idx, items=response.results, diagnostics=response.diagnostics)
                )
            try:
                self.metrics.inc("query_batch_calls")
                self.conn.commit()
            except sqlite3.OperationalError:
                self.conn.rollback()
        return QueryBatchResponse(results=results, duration_ms=_ms(perf_counter() - started))

    def _query_memory_locked(self, req: QueryRequest, *, write_log: bool) -> QueryResponse:
        started = perf_counter()

        bm25_start = perf_counter()
        lexical = self._lexical_candidates(
            project_id=req.project_id,
            query=req.query,
            top_k=max(req.k, self.settings.memory_retrieval_bm25_k),
        )
        bm25_ms = _ms(perf_counter() - bm25_start)

        dense_start = perf_counter()
        dense = self._dense_candidates(
            project_id=req.project_id,
            query=req.query,
            top_k=max(req.k, self.settings.memory_retrieval_dense_k),
        )
        dense_ms = _ms(perf_counter() - dense_start)

        fuse_start = perf_counter()
        fused, ranking_debug = rrf_fuse_with_debug(
            dense,
            lexical,
            intent=req.intent,
            dense_weight=self.settings.memory_retrieval_dense_weight,
            lexical_weight=self.settings.memory_retrieval_lexical_weight,
        )
        fusion_ms = _ms(perf_counter() - fuse_start)

        rerank_start = perf_counter()
        self._apply_usefulness_boosts(fused=fused, ranking_debug=ranking_debug)
        fused = trim_to_token_budget(fused, req.token_budget)
        selected = fused[: req.k]
        rerank_ms = _ms(perf_counter() - rerank_start)

        trust_by_chunk = self._chunk_trust_levels([item.chunk_id for item in selected])
        results = [
            QueryResult(
                chunk_id=item.chunk_id,
                score=round(item.score, 6),
                snippet=_snippet(_safe_render_memory_text(item.chunk_text)),
                source=QueryResultSource(
                    conversation_id=item.conversation_id,
                    created_at=item.created_at,
                    chunk_type=item.chunk_type,
                    trust_level=trust_by_chunk.get(item.chunk_id, "untrusted"),
                ),
            )
            for item in selected
        ]
        self._mark_chunks_accessed([item.chunk_id for item in selected])

        total_ms = _ms(perf_counter() - started)
        diagnostics = QueryDiagnostics(
            dense_ms=dense_ms,
            bm25_ms=bm25_ms,
            fusion_ms=fusion_ms,
            rerank_ms=rerank_ms,
            total_ms=total_ms,
        )

        if write_log:
            query_id = str(uuid4())
            ranking_payload = self._build_ranking_payload(
                selected=selected,
                ranking_debug=ranking_debug,
                trust_by_chunk=trust_by_chunk,
                diagnostics=diagnostics,
                dense_weight=self.settings.memory_retrieval_dense_weight,
                lexical_weight=self.settings.memory_retrieval_lexical_weight,
                intent=req.intent,
            )
            try:
                self.conn.execute(
                    """
                    INSERT INTO retrieval_logs(
                      query_id,
                      project_id,
                      query_text,
                      intent,
                      latency_ms,
                      result_chunk_ids_json,
                      ranking_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        query_id,
                        req.project_id,
                        req.query,
                        req.intent,
                        int(total_ms),
                        json.dumps([item.chunk_id for item in selected]),
                        json.dumps(ranking_payload),
                    ),
                )
                self.conn.commit()
            except sqlite3.OperationalError as exc:
                # Query path must fail open; logging should never block retrieval.
                self.conn.rollback()
                if "locked" not in str(exc).lower():
                    raise
        try:
            self.metrics.inc("queries_total")
            self.conn.commit()
        except sqlite3.OperationalError as exc:
            self.conn.rollback()
            if "locked" not in str(exc).lower():
                raise

        return QueryResponse(results=results, diagnostics=diagnostics)

    def _apply_usefulness_boosts(
        self,
        *,
        fused: list[RankedCandidate],
        ranking_debug: dict[str, dict[str, float | int | None]],
    ) -> None:
        if not fused:
            return

        chunk_ids = [item.chunk_id for item in fused]
        placeholders = ",".join("?" for _ in chunk_ids)
        rows = self.conn.execute(
            f"""
            SELECT chunk_id, access_count, user_vote, auto_judgement
            FROM chunks
            WHERE chunk_id IN ({placeholders})
            """,
            tuple(chunk_ids),
        ).fetchall()
        by_chunk = {str(row["chunk_id"]): row for row in rows}

        for candidate in fused:
            row = by_chunk.get(candidate.chunk_id)
            if row is None:
                continue
            access_count = max(0, int(row["access_count"] or 0))
            user_vote = row["user_vote"]
            auto_judgement = row["auto_judgement"]
            access_boost = min(0.04, 0.008 * math.log1p(access_count))
            vote_boost = 0.06 * _clamp_vote(user_vote)
            judgement_boost = 0.03 * _clamp_vote(auto_judgement)
            total_boost = access_boost + vote_boost + judgement_boost
            candidate.score += total_boost
            debug = ranking_debug.setdefault(candidate.chunk_id, {})
            debug["access_count"] = access_count
            debug["access_boost"] = round(access_boost, 6)
            debug["user_vote"] = _round_or_none(user_vote)
            debug["user_vote_boost"] = round(vote_boost, 6)
            debug["auto_judgement"] = _round_or_none(auto_judgement)
            debug["auto_judgement_boost"] = round(judgement_boost, 6)
            debug["final_score"] = round(candidate.score, 6)

        fused.sort(key=lambda item: item.score, reverse=True)
        for rank, item in enumerate(fused, start=1):
            debug = ranking_debug.setdefault(item.chunk_id, {})
            debug["final_rank"] = rank
            debug["final_score"] = round(item.score, 6)

    def _chunk_trust_levels(self, chunk_ids: list[str]) -> dict[str, str]:
        if not chunk_ids:
            return {}
        unique_chunk_ids = list(dict.fromkeys(chunk_ids))
        placeholders = ",".join("?" for _ in unique_chunk_ids)
        rows = self.conn.execute(
            f"""
            SELECT chunk_id, trust_level
            FROM chunks
            WHERE chunk_id IN ({placeholders})
            """,
            tuple(unique_chunk_ids),
        ).fetchall()
        return {str(row["chunk_id"]): str(row["trust_level"] or "untrusted") for row in rows}

    def _mark_chunks_accessed(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        unique_chunk_ids = list(dict.fromkeys(chunk_ids))
        placeholders = ",".join("?" for _ in unique_chunk_ids)
        now = _utc_iso()
        self.conn.execute(
            f"""
            UPDATE chunks
            SET access_count = access_count + 1,
                last_accessed_at = ?
            WHERE chunk_id IN ({placeholders})
            """,
            (now, *unique_chunk_ids),
        )

    def _build_ranking_payload(
        self,
        *,
        selected: list[RankedCandidate],
        ranking_debug: dict[str, dict[str, float | int | None]],
        trust_by_chunk: dict[str, str],
        diagnostics: QueryDiagnostics,
        dense_weight: float,
        lexical_weight: float,
        intent: str | None,
    ) -> dict[str, object]:
        shortlist: list[dict[str, object]] = []
        for rank, candidate in enumerate(selected, start=1):
            debug = ranking_debug.get(candidate.chunk_id, {})
            shortlist.append(
                {
                    "rank": rank,
                    "chunk_id": candidate.chunk_id,
                    "final_score": round(candidate.score, 6),
                    "chunk_type": candidate.chunk_type,
                    "created_at": candidate.created_at,
                    "trust_level": trust_by_chunk.get(candidate.chunk_id, "untrusted"),
                    "components": debug,
                }
            )
        return {
            "intent": intent,
            "weights": {
                "dense_weight": dense_weight,
                "lexical_weight": lexical_weight,
            },
            "diagnostics_ms": diagnostics.model_dump(),
            "shortlist": shortlist,
        }

    def bootstrap_memory(
        self, *, project_id: str, token_budget: int = 600, k: int = 6
    ) -> BootstrapResponse:
        with self.lock:
            rows = self.conn.execute(
                """
                SELECT chunk_id, chunk_text, chunk_type, conversation_id, created_at, importance, trust_level
                FROM chunks
                WHERE project_id = ?
                  AND archived = 0
                ORDER BY importance DESC, created_at DESC
                LIMIT 100
                """,
                (project_id,),
            ).fetchall()

            ranked = [
                RankedCandidate(
                    chunk_id=row["chunk_id"],
                    chunk_text=row["chunk_text"],
                    chunk_type=row["chunk_type"],
                    conversation_id=row["conversation_id"],
                    created_at=row["created_at"],
                    importance=float(row["importance"]),
                    score=float(row["importance"]),
                )
                for row in rows
            ]
            trust_by_chunk = {str(row["chunk_id"]): str(row["trust_level"] or "untrusted") for row in rows}
            selected = trim_to_token_budget(ranked, token_budget)[:k]
            results = [
                QueryResult(
                    chunk_id=item.chunk_id,
                    score=round(item.score, 6),
                    snippet=_snippet(_safe_render_memory_text(item.chunk_text)),
                    source=QueryResultSource(
                        conversation_id=item.conversation_id,
                        created_at=item.created_at,
                        chunk_type=item.chunk_type,
                        trust_level=trust_by_chunk.get(item.chunk_id, "untrusted"),
                    ),
                )
                for item in selected
            ]
            context_lines = [
                (
                    f'- [{item.chunk_id}] ({item.source.chunk_type}, trust={item.source.trust_level}) '
                    f'"{item.snippet}"'
                )
                for item in results
            ]
            self._mark_chunks_accessed([item.chunk_id for item in selected])
            self.metrics.inc("bootstrap_calls")

        return BootstrapResponse(context="\n".join(context_lines), results=results)

    def latest_memory(
        self,
        *,
        project_id: str,
        conversation_id: str | None = None,
        limit: int = 5,
        include_chunks: bool = True,
        include_facts: bool = True,
    ) -> LatestMemoryResponse:
        limit = max(1, min(limit, 200))
        fetch_limit = min(2000, max(20, limit * 4))
        items: list[LatestMemoryItem] = []

        with self.lock:
            if include_chunks:
                chunk_params: list[object] = [project_id]
                chunk_clause = ""
                if conversation_id:
                    chunk_clause = "AND conversation_id = ?"
                    chunk_params.append(conversation_id)
                chunk_params.append(fetch_limit)

                chunk_rows = self.conn.execute(
                    f"""
                    SELECT
                      chunk_id,
                      conversation_id,
                      chunk_type,
                      chunk_text,
                      importance,
                      created_at,
                      trust_level
                    FROM chunks
                    WHERE project_id = ?
                      AND archived = 0
                      {chunk_clause}
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    tuple(chunk_params),
                ).fetchall()
                for row in chunk_rows:
                    items.append(
                        LatestMemoryItem(
                            id=f"chunk:{row['chunk_id']}",
                            kind="chunk",
                            created_at=row["created_at"],
                            text=_snippet(_safe_render_memory_text(row["chunk_text"])),
                            conversation_id=row["conversation_id"],
                            chunk_id=row["chunk_id"],
                            chunk_type=row["chunk_type"],
                            importance=round(float(row["importance"]), 3),
                            trust_level=str(row["trust_level"] or "untrusted"),
                        )
                    )

            if include_facts:
                fact_params: list[object] = [project_id]
                fact_clause = ""
                if conversation_id:
                    fact_clause = "AND source_chunks.conversation_id = ?"
                    fact_params.append(conversation_id)
                fact_params.append(fetch_limit)
                fact_rows = self.conn.execute(
                    f"""
                    SELECT facts.fact_id, facts.fact_text, facts.confidence, facts.updated_at,
                           source_chunks.conversation_id AS source_conversation_id
                    FROM memory_facts AS facts
                    LEFT JOIN chunks AS source_chunks
                      ON source_chunks.chunk_id = facts.source_chunk_id
                    WHERE facts.project_id = ?
                      AND facts.status = 'active'
                      {fact_clause}
                    ORDER BY facts.updated_at DESC
                    LIMIT ?
                    """,
                    tuple(fact_params),
                ).fetchall()
                for row in fact_rows:
                    items.append(
                        LatestMemoryItem(
                            id=f"fact:{row['fact_id']}",
                            kind="fact",
                            created_at=row["updated_at"],
                            text=_snippet(_safe_render_memory_text(row["fact_text"])),
                            conversation_id=row["source_conversation_id"],
                            fact_id=row["fact_id"],
                            confidence=round(float(row["confidence"]), 3),
                            trust_level="derived",
                        )
                    )
            self.metrics.inc("latest_memory_calls")

        def _sort_key(item: LatestMemoryItem) -> datetime:
            normalized = item.created_at.replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                return datetime.min.replace(tzinfo=UTC)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed

        ordered = sorted(items, key=_sort_key, reverse=True)[:limit]
        return LatestMemoryResponse(project_id=project_id, items=ordered)

    def conversation_memory(
        self,
        *,
        conversation_id: str,
        project_id: str | None = None,
        limit: int = 2000,
        offset: int = 0,
        include_raw: bool = False,
    ) -> ConversationMemoryResponse:
        limit = max(1, min(limit, 5000))
        offset = max(0, min(offset, 50000))

        with self.lock:
            if project_id:
                conversation_row = self.conn.execute(
                    """
                    SELECT conversation_id, project_id, started_at, ended_at
                    FROM conversations
                    WHERE conversation_id = ?
                      AND project_id = ?
                    LIMIT 1
                    """,
                    (conversation_id, project_id),
                ).fetchone()
            else:
                conversation_row = self.conn.execute(
                    """
                    SELECT conversation_id, project_id, started_at, ended_at
                    FROM conversations
                    WHERE conversation_id = ?
                    LIMIT 1
                    """,
                    (conversation_id,),
                ).fetchone()

            if conversation_row is None:
                raise ApiError(
                    code="NOT_FOUND",
                    message=f"conversation not found: {conversation_id}",
                    status_code=404,
                    retryable=False,
                )

            resolved_project_id = str(conversation_row["project_id"])
            total_row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            total_messages = int(total_row["c"] if total_row else 0)

            message_rows = self.conn.execute(
                """
                SELECT message_id, role, content, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC, rowid ASC
                LIMIT ? OFFSET ?
                """,
                (conversation_id, limit, offset),
            ).fetchall()

            summary_row = self.conn.execute(
                """
                SELECT summary_text, message_count, summarizer_version, updated_at
                FROM conversation_summaries
                WHERE conversation_id = ?
                LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()

            messages = [
                ConversationMessageItem(
                    message_id=str(row["message_id"]),
                    role=str(row["role"]),
                    created_at=str(row["created_at"]),
                    content=_safe_render_memory_text(_clean_message_content(str(row["content"]))),
                    raw_content=(str(row["content"]) if include_raw else None),
                )
                for row in message_rows
            ]
            summary = (
                ConversationSummaryItem(
                    summary_text=str(summary_row["summary_text"]),
                    message_count=int(summary_row["message_count"]),
                    summarizer_version=(
                        str(summary_row["summarizer_version"])
                        if summary_row["summarizer_version"] is not None
                        else None
                    ),
                    updated_at=str(summary_row["updated_at"]),
                )
                if summary_row is not None
                else None
            )
            self.metrics.inc("conversation_memory_calls")

        return ConversationMemoryResponse(
            project_id=resolved_project_id,
            conversation_id=conversation_id,
            started_at=conversation_row["started_at"],
            ended_at=conversation_row["ended_at"],
            total_messages=total_messages,
            summary=summary,
            messages=messages,
        )

    def memory_graph(
        self,
        *,
        project_id: str,
        include_archived: bool = False,
        max_conversations: int = 200,
        max_chunks: int = 2000,
        max_facts: int = 1000,
    ) -> MemoryGraphResponse:
        max_conversations = max(1, min(max_conversations, 5000))
        max_chunks = max(1, min(max_chunks, 20000))
        max_facts = max(1, min(max_facts, 10000))

        with self.lock:
            conversation_rows = self.conn.execute(
                """
                SELECT conversation_id, session_id, started_at, created_at
                FROM conversations
                WHERE project_id = ?
                ORDER BY COALESCE(started_at, created_at) DESC
                LIMIT ?
                """,
                (project_id, max_conversations),
            ).fetchall()

            archive_clause = "" if include_archived else "AND archived = 0"
            chunk_rows = self.conn.execute(
                f"""
                SELECT chunk_id, project_id, conversation_id, chunk_text, chunk_type,
                       importance, archived, created_at, trust_level
                FROM chunks
                WHERE project_id = ?
                  {archive_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (project_id, max_chunks),
            ).fetchall()

            fact_rows = self.conn.execute(
                """
                SELECT fact_id, fact_text, confidence, source_chunk_id, updated_at
                FROM memory_facts
                WHERE project_id = ?
                  AND status = 'active'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (project_id, max_facts),
            ).fetchall()

            known_chunk_ids = {row["chunk_id"] for row in chunk_rows}
            source_chunk_ids = [
                source_chunk_id
                for source_chunk_id in {row["source_chunk_id"] for row in fact_rows if row["source_chunk_id"]}
                if source_chunk_id not in known_chunk_ids
            ]
            extra_chunk_rows: list[sqlite3.Row] = []
            if source_chunk_ids and len(known_chunk_ids) < max_chunks:
                headroom = max_chunks - len(known_chunk_ids)
                selected_chunk_ids = source_chunk_ids[:headroom]
                placeholders = ",".join("?" for _ in selected_chunk_ids)
                extra_chunk_rows = self.conn.execute(
                    f"""
                    SELECT chunk_id, project_id, conversation_id, chunk_text, chunk_type,
                           importance, archived, created_at, trust_level
                    FROM chunks
                    WHERE project_id = ?
                      AND chunk_id IN ({placeholders})
                    """,
                    (project_id, *selected_chunk_ids),
                ).fetchall()

            all_chunk_rows = [*chunk_rows, *extra_chunk_rows]
            conversation_by_id = {row["conversation_id"]: row for row in conversation_rows}
            missing_conversation_ids = {
                row["conversation_id"] for row in all_chunk_rows if row["conversation_id"] not in conversation_by_id
            }
            if missing_conversation_ids:
                placeholders = ",".join("?" for _ in missing_conversation_ids)
                extra_conversations = self.conn.execute(
                    f"""
                    SELECT conversation_id, session_id, started_at, created_at
                    FROM conversations
                    WHERE conversation_id IN ({placeholders})
                    """,
                    tuple(missing_conversation_ids),
                ).fetchall()
                for row in extra_conversations:
                    conversation_by_id[row["conversation_id"]] = row

            nodes: dict[str, MemoryGraphNodeData] = {}
            edges: dict[str, MemoryGraphEdgeData] = {}

            def _ensure_node(node: MemoryGraphNodeData) -> None:
                nodes.setdefault(node.id, node)

            def _ensure_edge(source: str, target: str, kind: str) -> None:
                edge_id = f"edge:{kind}:{source}->{target}"
                edges.setdefault(
                    edge_id,
                    MemoryGraphEdgeData(id=edge_id, source=source, target=target, kind=kind),
                )

            project_node_id = "project"
            project_label = Path(project_id).name.strip() or project_id
            _ensure_node(
                MemoryGraphNodeData(
                    id=project_node_id,
                    label=project_label,
                    kind="project",
                    text=None,
                    project_id=project_id,
                )
            )

            for row in conversation_by_id.values():
                conversation_id = row["conversation_id"]
                conversation_node_id = f"conv:{conversation_id}"
                label = conversation_id if len(conversation_id) <= 48 else f"{conversation_id[:45]}..."
                _ensure_node(
                    MemoryGraphNodeData(
                        id=conversation_node_id,
                        label=label,
                        kind="conversation",
                        text=None,
                        project_id=project_id,
                        conversation_id=conversation_id,
                        created_at=row["started_at"] or row["created_at"],
                    )
                )
                _ensure_edge(project_node_id, conversation_node_id, "contains")

            for row in all_chunk_rows:
                conversation_node_id = f"conv:{row['conversation_id']}"
                if conversation_node_id not in nodes:
                    _ensure_node(
                        MemoryGraphNodeData(
                            id=conversation_node_id,
                            label=row["conversation_id"],
                            kind="conversation",
                            text=None,
                            project_id=project_id,
                            conversation_id=row["conversation_id"],
                        )
                    )
                    _ensure_edge(project_node_id, conversation_node_id, "contains")

                chunk_node_id = f"chunk:{row['chunk_id']}"
                _ensure_node(
                    MemoryGraphNodeData(
                        id=chunk_node_id,
                        label=f"{row['chunk_type']}: {_snippet(row['chunk_text'], 88)}",
                        kind="chunk",
                        text=_safe_render_memory_text(row["chunk_text"]),
                        project_id=row["project_id"],
                        conversation_id=row["conversation_id"],
                        chunk_id=row["chunk_id"],
                        chunk_type=row["chunk_type"],
                        importance=round(float(row["importance"]), 3),
                        archived=bool(row["archived"]),
                        trust_level=str(row["trust_level"] or "untrusted"),
                        created_at=row["created_at"],
                    )
                )
                _ensure_edge(conversation_node_id, chunk_node_id, "contains")

            for row in fact_rows:
                fact_node_id = f"fact:{row['fact_id']}"
                _ensure_node(
                    MemoryGraphNodeData(
                        id=fact_node_id,
                        label=_snippet(row["fact_text"], 100),
                        kind="fact",
                        text=_safe_render_memory_text(row["fact_text"]),
                        project_id=project_id,
                        fact_id=row["fact_id"],
                        confidence=round(float(row["confidence"]), 3),
                        created_at=row["updated_at"],
                    )
                )
                _ensure_edge(project_node_id, fact_node_id, "contains")
                if row["source_chunk_id"]:
                    source_chunk_node_id = f"chunk:{row['source_chunk_id']}"
                    if source_chunk_node_id in nodes:
                        _ensure_edge(fact_node_id, source_chunk_node_id, "references")

            kind_order = {"project": 0, "conversation": 1, "chunk": 2, "fact": 3}
            ordered_node_data = sorted(
                nodes.values(),
                key=lambda item: (kind_order.get(item.kind, 99), item.created_at or "", item.id),
            )
            ordered_edge_data = sorted(
                edges.values(),
                key=lambda item: (item.kind, item.source, item.target),
            )

            node_items = [MemoryGraphNode(data=item) for item in ordered_node_data]
            edge_items = [MemoryGraphEdge(data=item) for item in ordered_edge_data]
            totals = {
                "projects": sum(1 for item in ordered_node_data if item.kind == "project"),
                "conversations": sum(1 for item in ordered_node_data if item.kind == "conversation"),
                "chunks": sum(1 for item in ordered_node_data if item.kind == "chunk"),
                "facts": sum(1 for item in ordered_node_data if item.kind == "fact"),
                "edges": len(edge_items),
            }
            self.metrics.inc("graph_calls")

        return MemoryGraphResponse(
            project_id=project_id,
            nodes=node_items,
            edges=edge_items,
            totals=totals,
        )

    def upsert_fact(self, req: UpsertFactRequest) -> UpsertFactResponse:
        fact_id = hashlib.sha256(f"{req.project_id}|{req.fact_text}".encode("utf-8")).hexdigest()[:24]
        with self.lock, transaction(self.conn):
            now = _utc_iso()
            fact_chunk_id, _ = self._upsert_fact_chunk(
                fact_id=fact_id,
                project_id=req.project_id,
                fact_text=req.fact_text,
                confidence=req.confidence,
                now=now,
            )
            source_chunk_id = req.source_chunk_id or fact_chunk_id
            self.conn.execute(
                """
                INSERT INTO memory_facts(fact_id, project_id, fact_text, confidence, source_chunk_id, status, updated_at)
                VALUES (?, ?, ?, ?, ?, 'active', ?)
                ON CONFLICT(fact_id)
                DO UPDATE SET
                  fact_text = excluded.fact_text,
                  confidence = excluded.confidence,
                  source_chunk_id = excluded.source_chunk_id,
                  status = 'active',
                  updated_at = excluded.updated_at
                """,
                (
                    fact_id,
                    req.project_id,
                    req.fact_text,
                    req.confidence,
                    source_chunk_id,
                    now,
                ),
            )
            if self._chunk_needs_embedding(fact_chunk_id):
                self._enqueue_embed_job(fact_chunk_id)
            self.metrics.inc("facts_upserted")
            self.metrics.inc("fact_chunks_upserted")
        return UpsertFactResponse(fact_id=fact_id, status="active", fact_chunk_id=fact_chunk_id)

    def compact(self, req: CompactRequest) -> CompactResponse:
        cutoff = (datetime.now(UTC) - timedelta(days=self.settings.memory_episodic_ttl_days)).isoformat(
            timespec="seconds"
        )
        now = _utc_iso()

        with self.lock, transaction(self.conn):
            rows = self.conn.execute(
                """
                SELECT id, chunk_id, chunk_text, conversation_id
                FROM chunks
                WHERE project_id = ?
                  AND archived = 0
                  AND importance < 0.55
                  AND created_at < ?
                ORDER BY created_at
                LIMIT ?
                """,
                (req.project_id, cutoff, req.max_chunks),
            ).fetchall()

            scanned = len(rows)
            if not rows:
                return CompactResponse(
                    scanned_chunks=0,
                    compacted_chunks=0,
                    summary_chunks_created=0,
                )

            summary_text = summarize_chunks([row["chunk_text"] for row in rows])
            summary_count = 0
            if summary_text:
                summary_hash = _chunk_hash(req.project_id, "compaction", "summary", summary_text)
                summary_chunk_id = f"summary-{summary_hash[:24]}"
                source_path = "compaction"
                source_hash = _source_hash(
                    source_path=source_path,
                    source_url=None,
                    conversation_id="compaction",
                    source_anchor="summary",
                    chunk_index=0,
                )
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO chunks(
                      chunk_id, chunk_hash, message_id, project_id, conversation_id,
                      chunk_text, chunk_type, importance, archived, source_path, source_hash, chunk_index,
                      raw_text, summary_text, trust_level, chunker_version, summarizer_version, created_at
                    ) VALUES (?, ?, NULL, ?, 'compaction', ?, 'summary', 0.65, 0, ?, ?, 0, ?, ?, 'derived', ?, ?, ?)
                    """,
                    (
                        summary_chunk_id,
                        summary_hash,
                        req.project_id,
                        summary_text,
                        source_path,
                        source_hash,
                        summary_text,
                        _snippet(summary_text, 420),
                        self.settings.memory_chunker_version,
                        self.settings.memory_summarizer_version,
                        now,
                    ),
                )
                self._enqueue_embed_job(summary_chunk_id)
                summary_count = 1

            ids = [row["id"] for row in rows]
            placeholders = ",".join("?" for _ in ids)
            self.conn.execute(
                f"UPDATE chunks SET archived = 1 WHERE id IN ({placeholders})",  # noqa: S608
                ids,
            )
            self.metrics.inc("compaction_runs")
            self.metrics.inc("chunks_compacted", len(rows))

        return CompactResponse(
            scanned_chunks=scanned,
            compacted_chunks=len(rows),
            summary_chunks_created=summary_count,
        )

    def admin_reembed(self, req: AdminReembedRequest) -> AdminReembedResponse:
        started = perf_counter()
        target_model = req.target_model or self.embedding_provider.model
        target_dim = int(self.settings.memory_embedding_dimensions)
        target_metric = self.settings.memory_embed_distance_metric
        now = _utc_iso()

        with self.lock, transaction(self.conn):
            where_parts: list[str] = ["c.archived = 0"]
            params: list[object] = []
            if req.project_id:
                where_parts.append("c.project_id = ?")
                params.append(req.project_id)

            if req.scope == "missing_or_model_mismatch":
                where_parts.append(
                    "("
                    "e.chunk_id IS NULL OR "
                    "COALESCE(e.embed_model, e.embed_model_id, e.model) != ? OR "
                    "COALESCE(e.embed_dim, e.dim, e.dimensions) != ? OR "
                    "COALESCE(e.distance_metric, 'cosine') != ?"
                    ")"
                )
                params.extend([target_model, target_dim, target_metric])
            where_clause = " AND ".join(where_parts)

            rows = self.conn.execute(
                f"""
                SELECT
                  c.chunk_id,
                  COALESCE(e.embed_model, e.embed_model_id, e.model) AS model,
                  COALESCE(e.embed_dim, e.dim, e.dimensions) AS dim,
                  COALESCE(e.distance_metric, 'cosine') AS distance_metric
                FROM chunks c
                LEFT JOIN chunk_embeddings e ON e.chunk_id = c.chunk_id
                WHERE {where_clause}
                  AND NOT EXISTS (
                    SELECT 1
                    FROM jobs j
                    WHERE j.job_type = 'embed_chunk'
                      AND j.status IN ('pending', 'queued', 'running')
                      AND json_extract(j.payload_json, '$.chunk_id') = c.chunk_id
                  )
                LIMIT ?
                """,
                (*params, req.limit),
            ).fetchall()

            queued = 0
            skipped_already_current = 0
            for row in rows:
                chunk_id = row["chunk_id"]
                model = row["model"]
                dim = int(row["dim"]) if row["dim"] is not None else None
                distance_metric = str(row["distance_metric"]) if row["distance_metric"] is not None else None
                if (
                    req.scope == "missing_or_model_mismatch"
                    and model == target_model
                    and dim == target_dim
                    and distance_metric == target_metric
                ):
                    skipped_already_current += 1
                    continue
                if self._enqueue_embed_job(chunk_id):
                    queued += 1

            self.metrics.inc("admin_reembed_calls")
            self.metrics.inc("admin_reembed_queued", queued)

            if req.scope == "all":
                skipped_row = self.conn.execute(
                    f"""
                    SELECT COUNT(*) AS c
                    FROM chunks c
                    JOIN chunk_embeddings e ON e.chunk_id = c.chunk_id
                    WHERE {where_clause}
                      AND COALESCE(e.embed_model, e.embed_model_id, e.model) = ?
                      AND COALESCE(e.embed_dim, e.dim, e.dimensions) = ?
                      AND COALESCE(e.distance_metric, 'cosine') = ?
                    """,
                    (*params, target_model, target_dim, target_metric),
                ).fetchone()
                skipped_already_current = int(skipped_row["c"] if skipped_row else 0)

            self.conn.commit()

        return AdminReembedResponse(
            queued_jobs=queued,
            skipped_already_current=skipped_already_current,
            duration_ms=_ms(perf_counter() - started),
        )

    def admin_resummarize(self, req: AdminResummarizeRequest) -> AdminResummarizeResponse:
        started = perf_counter()

        with self.lock, transaction(self.conn):
            where_parts: list[str] = []
            params: list[object] = []
            if req.project_id:
                where_parts.append("c.project_id = ?")
                params.append(req.project_id)
            if req.conversation_id:
                where_parts.append("c.conversation_id = ?")
                params.append(req.conversation_id)
            where_clause = " AND ".join(where_parts)
            if where_clause:
                where_clause = "WHERE " + where_clause

            rows = self.conn.execute(
                f"""
                SELECT
                  c.conversation_id,
                  c.project_id,
                  cs.summarizer_version
                FROM conversations c
                LEFT JOIN conversation_summaries cs
                  ON cs.conversation_id = c.conversation_id
                {where_clause}
                ORDER BY COALESCE(c.started_at, c.created_at) DESC
                LIMIT ?
                """,
                (*params, req.limit),
            ).fetchall()

            refreshed = 0
            skipped_existing = 0
            for row in rows:
                if row["summarizer_version"] == self.settings.memory_summarizer_version:
                    skipped_existing += 1
                    continue
                self._refresh_conversation_summary(
                    conversation_id=str(row["conversation_id"]),
                    project_id=str(row["project_id"]),
                )
                refreshed += 1

            self.metrics.inc("admin_resummarize_calls")
            self.metrics.inc("admin_resummarize_refreshed", refreshed)
            self.conn.commit()

        return AdminResummarizeResponse(
            queued_jobs=refreshed,
            skipped_existing=skipped_existing,
            duration_ms=_ms(perf_counter() - started),
        )

    def record_chunk_feedback(self, req: ChunkFeedbackRequest) -> ChunkFeedbackResponse:
        with self.lock, transaction(self.conn):
            row = self.conn.execute(
                "SELECT chunk_id FROM chunks WHERE chunk_id = ? LIMIT 1",
                (req.chunk_id,),
            ).fetchone()
            if row is None:
                raise ApiError(
                    code="NOT_FOUND",
                    message=f"chunk not found: {req.chunk_id}",
                    status_code=404,
                    retryable=False,
                )

            has_user_vote = req.user_vote is not None
            has_auto = req.auto_judgement is not None
            self.conn.execute(
                """
                UPDATE chunks
                SET
                  user_vote = CASE WHEN ? THEN ? ELSE user_vote END,
                  auto_judgement = CASE WHEN ? THEN ? ELSE auto_judgement END
                WHERE chunk_id = ?
                """,
                (
                    1 if has_user_vote else 0,
                    req.user_vote,
                    1 if has_auto else 0,
                    req.auto_judgement,
                    req.chunk_id,
                ),
            )
            self.metrics.inc("chunk_feedback_updates")

        return ChunkFeedbackResponse(chunk_id=req.chunk_id, updated=True)

    def admin_stats(self) -> AdminStatsResponse:
        with self.lock:
            counts_row = self.conn.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM conversations) AS conversations,
                  (SELECT COUNT(*) FROM messages) AS messages,
                  (SELECT COUNT(*) FROM chunks) AS chunks_total,
                  (SELECT COUNT(*) FROM chunks WHERE archived = 0) AS chunks_active,
                  (SELECT COUNT(*) FROM chunks WHERE archived = 1) AS chunks_archived,
                  (SELECT COUNT(*) FROM chunk_embeddings) AS embeddings_total,
                  (SELECT COUNT(*) FROM jobs WHERE status IN ('pending', 'queued')) AS jobs_queued,
                  (SELECT COUNT(*) FROM jobs WHERE status = 'running') AS jobs_running,
                  (SELECT COUNT(*) FROM jobs WHERE status = 'failed') AS jobs_failed
                """
            ).fetchone()
            counts = {key: int(counts_row[key]) for key in counts_row.keys()}

            chunks_by_type = {
                row["chunk_type"]: int(row["c"])
                for row in self.conn.execute(
                    "SELECT chunk_type, COUNT(*) AS c FROM chunks GROUP BY chunk_type"
                ).fetchall()
            }
            jobs_by_status = {
                row["status"]: int(row["c"])
                for row in self.conn.execute(
                    "SELECT status, COUNT(*) AS c FROM jobs GROUP BY status"
                ).fetchall()
            }
            embeddings_by_model = {
                f"{row['model']}:{row['dim']}:{row['distance_metric']}": int(row["c"])
                for row in self.conn.execute(
                    """
                    SELECT
                      COALESCE(embed_model, embed_model_id, model) AS model,
                      COALESCE(embed_dim, dim, dimensions) AS dim,
                      COALESCE(distance_metric, 'cosine') AS distance_metric,
                      COUNT(*) AS c
                    FROM chunk_embeddings
                    GROUP BY
                      COALESCE(embed_model, embed_model_id, model),
                      COALESCE(embed_dim, dim, dimensions),
                      COALESCE(distance_metric, 'cosine')
                    """
                ).fetchall()
            }
            facts_by_status = {
                row["status"]: int(row["c"])
                for row in self.conn.execute(
                    "SELECT status, COUNT(*) AS c FROM memory_facts GROUP BY status"
                ).fetchall()
            }
            latencies = self._endpoint_latency_summary()

            self.metrics.inc("admin_stats_calls")
            self.conn.commit()

        return AdminStatsResponse(
            generated_at=_utc_iso(),
            counts=counts,
            chunks_by_type=chunks_by_type,
            jobs_by_status=jobs_by_status,
            embeddings_by_model=embeddings_by_model,
            facts_by_status=facts_by_status,
            endpoint_latency_ms={
                endpoint: EndpointLatencyStats(**summary) for endpoint, summary in latencies.items()
            },
        )

    def admin_checkpoint(self, mode: str) -> AdminCheckpointResponse:
        started = perf_counter()
        mode_key = mode.upper()
        if mode_key not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
            raise ApiError(
                code="VALIDATION_ERROR",
                message=f"invalid checkpoint mode: {mode}",
                status_code=422,
                hint="use PASSIVE, FULL, RESTART, or TRUNCATE",
            )

        with self.lock:
            row = self.conn.execute(f"PRAGMA wal_checkpoint({mode_key});").fetchone()
            self.metrics.inc("admin_checkpoint_calls")
            self.conn.commit()

        busy = int(row[0]) if row is not None else 0
        log_frames = int(row[1]) if row is not None else 0
        checkpointed_frames = int(row[2]) if row is not None else 0
        return AdminCheckpointResponse(
            mode=mode_key,
            busy=busy,
            log_frames=log_frames,
            checkpointed_frames=checkpointed_frames,
            duration_ms=_ms(perf_counter() - started),
        )

    def admin_vacuum(self, req: AdminVacuumRequest) -> AdminVacuumResponse:
        started = perf_counter()
        with self.lock:
            queued_row = self.conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM jobs
                WHERE job_type='embed_chunk'
                  AND status IN ('pending', 'queued')
                """
            ).fetchone()
            queued_jobs = int(queued_row["c"] if queued_row else 0)
            if queued_jobs > req.max_queued_jobs:
                raise ApiError(
                    code="RATE_LIMITED_LOCAL",
                    message=(
                        f"queued embed jobs ({queued_jobs}) exceed max_queued_jobs "
                        f"({req.max_queued_jobs})"
                    ),
                    status_code=429,
                    retryable=True,
                    hint="drain queue or raise max_queued_jobs",
                )

            self.conn.execute("VACUUM;")
            if req.analyze:
                self.conn.execute("ANALYZE;")
            self.metrics.inc("admin_vacuum_calls")
            self.conn.commit()

        return AdminVacuumResponse(
            accepted=True,
            duration_ms=_ms(perf_counter() - started),
            details={"queued_jobs": queued_jobs, "analyze": req.analyze},
        )

    def health(self) -> HealthResponse:
        db_ok = True
        details: dict[str, str] = {}

        with self.lock:
            try:
                self.conn.execute("SELECT 1").fetchone()
            except Exception as exc:  # noqa: BLE001
                db_ok = False
                details["db_error"] = str(exc)

            row = self.conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM jobs
                WHERE job_type='embed_chunk'
                  AND status IN ('pending', 'queued')
                """
            ).fetchone()
            pending = int(row["c"] if row else 0)

        provider_ok, provider_detail = self.embedding_provider.health()
        if not provider_ok:
            details["embedding_provider"] = provider_detail

        vector_ok = True
        if self.retrieval_backend == "qdrant":
            if self.vector_index is None:
                vector_ok = False
                if self.vector_index_error:
                    details["vector_backend"] = self.vector_index_error
                else:
                    details["vector_backend"] = "qdrant backend unavailable"
            else:
                vector_ok, vector_detail = self.vector_index.health()
                if not vector_ok:
                    details["vector_backend"] = vector_detail

        status = "ok" if db_ok and provider_ok and vector_ok else "degraded"
        return HealthResponse(
            status=status,
            db_ok=db_ok,
            embedding_provider_ok=provider_ok,
            pending_embedding_jobs=pending,
            details=details,
        )

    def metrics_text(self) -> str:
        with self.lock:
            base = self.metrics.export_prometheus()
            latency_summary = self._endpoint_latency_summary()

        lines = [base.rstrip("\n"), "# TYPE memory_endpoint_latency_ms gauge"]
        for endpoint, data in latency_summary.items():
            safe = endpoint.replace("\"", "")
            lines.append(
                f'memory_endpoint_latency_ms{{endpoint="{safe}",quantile="p50"}} {data["p50_ms"]}'
            )
            lines.append(
                f'memory_endpoint_latency_ms{{endpoint="{safe}",quantile="p95"}} {data["p95_ms"]}'
            )
            lines.append(
                f'memory_endpoint_latency_samples{{endpoint="{safe}"}} {data["samples"]}'
            )
        return "\n".join(lines) + "\n"

    def _get_idempotent_response(
        self,
        *,
        endpoint: str,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, object] | None:
        self._purge_expired_idempotency()
        row = self.conn.execute(
            """
            SELECT request_hash, response_json
            FROM idempotency_keys
            WHERE endpoint = ? AND idempotency_key = ?
            """,
            (endpoint, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise ApiError(
                code="VALIDATION_ERROR",
                message="idempotency key reused with different payload",
                status_code=409,
                retryable=False,
                hint="use a new Idempotency-Key for modified payload",
            )
        return json.loads(row["response_json"])

    def _save_idempotent_response(
        self,
        *,
        endpoint: str,
        idempotency_key: str,
        request_hash: str,
        response_payload: dict[str, object],
        status_code: int,
    ) -> None:
        now = datetime.now(UTC)
        expires = (now + timedelta(hours=self.settings.memory_idempotency_ttl_hours)).isoformat(
            timespec="seconds"
        )
        self.conn.execute(
            """
            INSERT INTO idempotency_keys(
              endpoint, idempotency_key, request_hash, response_json, status_code, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(endpoint, idempotency_key)
            DO UPDATE SET
              request_hash = excluded.request_hash,
              response_json = excluded.response_json,
              status_code = excluded.status_code,
              created_at = excluded.created_at,
              expires_at = excluded.expires_at
            """,
            (
                endpoint,
                idempotency_key,
                request_hash,
                json.dumps(response_payload),
                status_code,
                now.isoformat(timespec="seconds"),
                expires,
            ),
        )

    def _purge_expired_idempotency(self) -> None:
        self.conn.execute(
            "DELETE FROM idempotency_keys WHERE expires_at < ?",
            (_utc_iso(),),
        )
        self.conn.commit()

    def _endpoint_latency_summary(self) -> dict[str, dict[str, float | int]]:
        rows = self.conn.execute(
            """
            SELECT endpoint, latency_ms
            FROM endpoint_latencies
            ORDER BY endpoint, id DESC
            """
        ).fetchall()

        grouped: dict[str, list[float]] = {}
        for row in rows:
            grouped.setdefault(row["endpoint"], []).append(float(row["latency_ms"]))

        summary: dict[str, dict[str, float | int]] = {}
        for endpoint, values in grouped.items():
            values.sort()
            p50 = _percentile(values, 0.50)
            p95 = _percentile(values, 0.95)
            summary[endpoint] = {
                "samples": len(values),
                "p50_ms": p50,
                "p95_ms": p95,
            }
        return summary

    def _bootstrap_fact_chunks(self) -> None:
        now = _utc_iso()
        with self.lock, transaction(self.conn):
            rows = self.conn.execute(
                """
                SELECT fact_id, project_id, fact_text, confidence, source_chunk_id
                FROM memory_facts
                WHERE status = 'active'
                ORDER BY updated_at DESC
                LIMIT 50000
                """
            ).fetchall()
            if not rows:
                return

            created_or_updated = 0
            queued = 0
            for row in rows:
                fact_chunk_id, changed = self._upsert_fact_chunk(
                    fact_id=row["fact_id"],
                    project_id=row["project_id"],
                    fact_text=row["fact_text"],
                    confidence=float(row["confidence"]),
                    now=now,
                )
                if changed:
                    created_or_updated += 1
                if self._chunk_needs_embedding(fact_chunk_id):
                    if self._enqueue_embed_job(fact_chunk_id):
                        queued += 1

                self.conn.execute(
                    """
                    UPDATE memory_facts
                    SET source_chunk_id = COALESCE(source_chunk_id, ?), updated_at = ?
                    WHERE fact_id = ?
                    """,
                    (fact_chunk_id, now, row["fact_id"]),
                )

            self.metrics.inc("fact_chunks_bootstrap_runs")
            self.metrics.inc("fact_chunks_bootstrap_upserts", created_or_updated)
            self.metrics.inc("fact_chunks_bootstrap_embed_jobs", queued)

    def _bootstrap_fact_chunks_with_retry(self) -> None:
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                self._bootstrap_fact_chunks()
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == attempts:
                    return
                sleep(0.15 * attempt)

    def _bootstrap_conversation_summaries(self) -> None:
        with self.lock, transaction(self.conn):
            rows = self.conn.execute(
                """
                SELECT conversation_id, project_id
                FROM conversations
                ORDER BY COALESCE(started_at, created_at) DESC
                LIMIT 50000
                """
            ).fetchall()
            if not rows:
                return

            refreshed = 0
            for row in rows:
                self._refresh_conversation_summary(
                    conversation_id=str(row["conversation_id"]),
                    project_id=str(row["project_id"]),
                )
                refreshed += 1

            self.metrics.inc("conversation_summary_bootstrap_runs")
            self.metrics.inc("conversation_summary_bootstrap_refreshed", refreshed)

    def _bootstrap_conversation_summaries_with_retry(self) -> None:
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                self._bootstrap_conversation_summaries()
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == attempts:
                    return
                sleep(0.15 * attempt)

    def _upsert_fact_chunk(
        self,
        *,
        fact_id: str,
        project_id: str,
        fact_text: str,
        confidence: float,
        now: str,
    ) -> tuple[str, bool]:
        conversation_id = _fact_conversation_id(project_id)
        self._upsert_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            session_id=conversation_id,
            transcript_path="",
            started_at=now,
        )

        chunk_id = _fact_chunk_id(fact_id)
        normalized_text = f"[project:{project_id}] [fact] {fact_text.strip()}"
        chunk_hash = _chunk_hash(project_id, conversation_id, "fact", normalized_text)
        importance = max(0.5, min(1.0, confidence))
        source_path = "memory_facts"
        source_hash = _source_hash(
            source_path=source_path,
            source_url=None,
            conversation_id=conversation_id,
            source_anchor=fact_id,
            chunk_index=0,
        )
        metadata_json = json.dumps({"fact_id": fact_id, "kind": "fact"})

        row = self.conn.execute(
            """
            SELECT chunk_hash, chunk_text, importance, archived
            FROM chunks
            WHERE chunk_id = ?
            """,
            (chunk_id,),
        ).fetchone()

        if row is None:
            self.conn.execute(
                """
                INSERT INTO chunks(
                  chunk_id, chunk_hash, message_id, project_id, conversation_id,
                  chunk_text, chunk_type, importance, archived, source_path, source_hash, chunk_index,
                  metadata_json, raw_text, summary_text, trust_level, chunker_version, summarizer_version, created_at
                ) VALUES (?, ?, NULL, ?, ?, ?, 'fact', ?, 0, ?, ?, 0, ?, ?, ?, 'derived', ?, ?, ?)
                """,
                (
                    chunk_id,
                    chunk_hash,
                    project_id,
                    conversation_id,
                    normalized_text,
                    importance,
                    source_path,
                    source_hash,
                    metadata_json,
                    normalized_text,
                    _snippet(normalized_text, 420),
                    self.settings.memory_chunker_version,
                    self.settings.memory_summarizer_version,
                    now,
                ),
            )
            return chunk_id, True

        changed = (
            row["chunk_hash"] != chunk_hash
            or row["chunk_text"] != normalized_text
            or float(row["importance"]) != float(importance)
            or int(row["archived"]) != 0
        )
        if changed:
            self.conn.execute(
                """
                UPDATE chunks
                SET chunk_hash = ?,
                    chunk_text = ?,
                    chunk_type = 'fact',
                    importance = ?,
                    archived = 0,
                    source_path = ?,
                    source_hash = ?,
                    chunk_index = 0,
                    metadata_json = ?,
                    raw_text = ?,
                    summary_text = ?,
                    trust_level = 'derived',
                    chunker_version = ?,
                    summarizer_version = ?
                WHERE chunk_id = ?
                """,
                (
                    chunk_hash,
                    normalized_text,
                    importance,
                    source_path,
                    source_hash,
                    metadata_json,
                    normalized_text,
                    _snippet(normalized_text, 420),
                    self.settings.memory_chunker_version,
                    self.settings.memory_summarizer_version,
                    chunk_id,
                ),
            )
        return chunk_id, changed

    def _chunk_needs_embedding(self, chunk_id: str) -> bool:
        row = self.conn.execute(
            """
            SELECT
              COALESCE(embed_model, embed_model_id, model) AS embed_model_id,
              COALESCE(embed_dim, dim, dimensions) AS embed_dim,
              COALESCE(distance_metric, 'cosine') AS distance_metric
            FROM chunk_embeddings
            WHERE chunk_id = ?
            """,
            (chunk_id,),
        ).fetchone()
        if row is None:
            return True
        if row["embed_model_id"] != self.embedding_provider.model:
            return True
        if int(row["embed_dim"]) != int(self.settings.memory_embedding_dimensions):
            return True
        return str(row["distance_metric"]) != self.settings.memory_embed_distance_metric

    def _upsert_conversation(
        self,
        *,
        conversation_id: str,
        project_id: str,
        session_id: str,
        transcript_path: str,
        started_at: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO conversations(conversation_id, project_id, session_id, transcript_path, started_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id)
            DO UPDATE SET
              transcript_path = CASE WHEN excluded.transcript_path != '' THEN excluded.transcript_path ELSE conversations.transcript_path END
            """,
            (conversation_id, project_id, session_id, transcript_path, started_at),
        )

    def _store_message_chunks(
        self,
        *,
        project_id: str,
        conversation_id: str,
        parsed: ParsedMessage,
        source_path: str | None = None,
        source_url: str | None = None,
        source_mtime: str | None = None,
    ) -> tuple[str | None, int, int, int]:
        content = parsed.content.strip()
        if not content:
            return None, 0, 0, 0

        if self.settings.memory_enable_redaction:
            content = redact_text(content)

        message_id = self._resolve_message_id(
            project_id=project_id,
            conversation_id=conversation_id,
            parsed=parsed,
            source_path=source_path,
            source_url=source_url,
        )
        created_at = parsed.created_at or _utc_iso()
        trust_level = _infer_trust_level(source_path=source_path, source_url=source_url)
        self.conn.execute(
            """
            INSERT INTO messages(message_id, conversation_id, role, content, token_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id)
            DO UPDATE SET
              content = excluded.content,
              token_count = excluded.token_count,
              created_at = excluded.created_at
            """,
            (
                message_id,
                conversation_id,
                parsed.role,
                content,
                max(1, len(content) // 4),
                created_at,
            ),
        )

        created = 0
        dedup = 0
        enqueued = 0
        chunk_index = 0

        contextual_prefix = f"[project:{project_id}] [role:{parsed.role}]"
        for split_text in split_turn_text(content):
            chunk_text = f"{contextual_prefix}\n{split_text}"
            stable_chunk_id = self._stable_chunk_id(
                project_id=project_id,
                conversation_id=conversation_id,
                source_path=source_path,
                source_url=source_url,
                source_anchor=self._source_anchor(parsed),
                chunk_type="turn",
                chunk_index=chunk_index,
            )
            source_hash = _source_hash(
                source_path=source_path,
                source_url=source_url,
                conversation_id=conversation_id,
                source_anchor=self._source_anchor(parsed),
                chunk_index=chunk_index,
            )
            inserted, chunk_id = self._insert_chunk(
                stable_chunk_id=stable_chunk_id,
                message_id=message_id,
                project_id=project_id,
                conversation_id=conversation_id,
                chunk_text=chunk_text,
                chunk_type="turn",
                importance=0.20,
                created_at=created_at,
                raw_text=split_text,
                summary_text=_snippet(split_text, 420),
                source_path=source_path,
                source_url=source_url,
                source_mtime=source_mtime,
                source_hash=source_hash,
                chunk_index=chunk_index,
                trust_level=trust_level,
                chunker_version=self.settings.memory_chunker_version,
                summarizer_version=self.settings.memory_summarizer_version,
            )
            chunk_index += 1
            if inserted and chunk_id:
                created += 1
                if self._enqueue_embed_job(chunk_id):
                    enqueued += 1
            else:
                dedup += 1

        for extra in extract_high_signal_chunks(content):
            chunk_text = f"{contextual_prefix}\n{extra.chunk_text}"
            stable_chunk_id = self._stable_chunk_id(
                project_id=project_id,
                conversation_id=conversation_id,
                source_path=source_path,
                source_url=source_url,
                source_anchor=self._source_anchor(parsed),
                chunk_type=extra.chunk_type,
                chunk_index=chunk_index,
            )
            source_hash = _source_hash(
                source_path=source_path,
                source_url=source_url,
                conversation_id=conversation_id,
                source_anchor=self._source_anchor(parsed),
                chunk_index=chunk_index,
            )
            inserted, chunk_id = self._insert_chunk(
                stable_chunk_id=stable_chunk_id,
                message_id=message_id,
                project_id=project_id,
                conversation_id=conversation_id,
                chunk_text=chunk_text,
                chunk_type=extra.chunk_type,
                importance=extra.importance,
                created_at=created_at,
                raw_text=extra.chunk_text,
                summary_text=_snippet(extra.chunk_text, 420),
                source_path=source_path,
                source_url=source_url,
                source_mtime=source_mtime,
                source_hash=source_hash,
                chunk_index=chunk_index,
                trust_level=trust_level,
                chunker_version=self.settings.memory_chunker_version,
                summarizer_version=self.settings.memory_summarizer_version,
            )
            chunk_index += 1
            if inserted and chunk_id:
                created += 1
                if self._enqueue_embed_job(chunk_id):
                    enqueued += 1
            else:
                dedup += 1

        return message_id, created, dedup, enqueued

    def _source_anchor(self, parsed: ParsedMessage) -> str:
        explicit = getattr(parsed, "source_ref", "") or ""
        if explicit:
            return explicit
        created = (parsed.created_at or "").strip()
        content_digest = hashlib.sha1(parsed.content.encode("utf-8")).hexdigest()[:16]
        return f"{parsed.role}:{created}:{content_digest}"

    def _resolve_message_id(
        self,
        *,
        project_id: str,
        conversation_id: str,
        parsed: ParsedMessage,
        source_path: str | None,
        source_url: str | None,
    ) -> str:
        source_identity = source_url or source_path
        if not source_identity or str(source_identity).startswith("conversation:"):
            return str(uuid4())
        digest = hashlib.sha256(
            "|".join(
                [
                    project_id,
                    conversation_id,
                    source_identity,
                    self._source_anchor(parsed),
                ]
            ).encode("utf-8")
        ).hexdigest()
        return f"msg-{digest[:24]}"

    def _stable_chunk_id(
        self,
        *,
        project_id: str,
        conversation_id: str,
        source_path: str | None,
        source_url: str | None,
        source_anchor: str,
        chunk_type: str,
        chunk_index: int,
    ) -> str:
        source_identity = source_url or source_path
        if not source_identity or str(source_identity).startswith("conversation:"):
            return str(uuid4())
        digest = hashlib.sha256(
            "|".join(
                [
                    project_id,
                    conversation_id,
                    source_identity,
                    source_anchor,
                    chunk_type,
                    str(chunk_index),
                ]
            ).encode("utf-8")
        ).hexdigest()
        return f"chk-{digest[:24]}"

    def _insert_chunk(
        self,
        *,
        stable_chunk_id: str | None = None,
        message_id: str | None,
        project_id: str,
        conversation_id: str,
        chunk_text: str,
        chunk_type: str,
        importance: float,
        created_at: str,
        raw_text: str | None = None,
        summary_text: str | None = None,
        source_path: str | None = None,
        source_url: str | None = None,
        source_mtime: str | None = None,
        source_hash: str | None = None,
        chunk_index: int = 0,
        trust_level: str = "untrusted",
        chunker_version: str | None = None,
        summarizer_version: str | None = None,
    ) -> tuple[bool, str | None]:
        chunk_id = stable_chunk_id or str(uuid4())
        chunk_hash = _chunk_hash(project_id, conversation_id, chunk_type, chunk_text)
        resolved_chunker_version = chunker_version or self.settings.memory_chunker_version
        resolved_summarizer_version = summarizer_version or self.settings.memory_summarizer_version
        normalized_trust_level = (trust_level or "untrusted").strip().lower()

        existing_hash_row = self.conn.execute(
            """
            SELECT chunk_id
            FROM chunks
            WHERE chunk_hash = ?
            LIMIT 1
            """,
            (chunk_hash,),
        ).fetchone()
        if existing_hash_row is not None and str(existing_hash_row["chunk_id"]) != chunk_id:
            return False, str(existing_hash_row["chunk_id"])

        row = self.conn.execute(
            """
            SELECT
              chunk_hash,
              message_id,
              chunk_text,
              chunk_type,
              importance,
              archived,
              source_path,
              source_url,
              source_mtime,
              source_hash,
              chunk_index,
              raw_text,
              summary_text,
              trust_level,
              chunker_version,
              summarizer_version
            FROM chunks
            WHERE chunk_id = ?
            """,
            (chunk_id,),
        ).fetchone()

        if row is None:
            self.conn.execute(
                """
                INSERT INTO chunks(
                    chunk_id, chunk_hash, message_id, project_id, conversation_id,
                    chunk_text, chunk_type, importance, source_path, source_url, source_mtime, source_hash,
                    chunk_index, metadata_json, raw_text, summary_text, trust_level,
                    chunker_version, summarizer_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    chunk_hash,
                    message_id,
                    project_id,
                    conversation_id,
                    chunk_text,
                    chunk_type,
                    importance,
                    source_path,
                    source_url,
                    source_mtime,
                    source_hash,
                    chunk_index,
                    "{}",
                    raw_text or chunk_text,
                    summary_text or _snippet(chunk_text, 420),
                    normalized_trust_level,
                    resolved_chunker_version,
                    resolved_summarizer_version,
                    created_at,
                ),
            )
            return True, chunk_id

        changed = (
            row["chunk_hash"] != chunk_hash
            or row["message_id"] != message_id
            or row["chunk_text"] != chunk_text
            or row["chunk_type"] != chunk_type
            or float(row["importance"]) != float(importance)
            or int(row["archived"]) != 0
            or row["source_path"] != source_path
            or row["source_url"] != source_url
            or row["source_mtime"] != source_mtime
            or row["source_hash"] != source_hash
            or int(row["chunk_index"]) != int(chunk_index)
            or row["raw_text"] != (raw_text or chunk_text)
            or row["summary_text"] != (summary_text or _snippet(chunk_text, 420))
            or row["trust_level"] != normalized_trust_level
            or row["chunker_version"] != resolved_chunker_version
            or row["summarizer_version"] != resolved_summarizer_version
        )
        if not changed:
            return False, chunk_id

        self.conn.execute(
            """
            UPDATE chunks
            SET
              chunk_hash = ?,
              message_id = ?,
              project_id = ?,
              conversation_id = ?,
              chunk_text = ?,
              chunk_type = ?,
              importance = ?,
              archived = 0,
              source_path = ?,
              source_url = ?,
              source_mtime = ?,
              source_hash = ?,
              chunk_index = ?,
              raw_text = ?,
              summary_text = ?,
              trust_level = ?,
              chunker_version = ?,
              summarizer_version = ?,
              created_at = ?
            WHERE chunk_id = ?
            """,
            (
                chunk_hash,
                message_id,
                project_id,
                conversation_id,
                chunk_text,
                chunk_type,
                importance,
                source_path,
                source_url,
                source_mtime,
                source_hash,
                chunk_index,
                raw_text or chunk_text,
                summary_text or _snippet(chunk_text, 420),
                normalized_trust_level,
                resolved_chunker_version,
                resolved_summarizer_version,
                created_at,
                chunk_id,
            ),
        )
        return True, chunk_id

    def _enqueue_embed_job(self, chunk_id: str) -> bool:
        exists = self.conn.execute(
            """
            SELECT 1
            FROM jobs
            WHERE job_type = 'embed_chunk'
              AND status IN ('pending', 'queued', 'running')
              AND json_extract(payload_json, '$.chunk_id') = ?
            LIMIT 1
            """,
            (chunk_id,),
        ).fetchone()
        if exists is not None:
            return False

        job_id = str(uuid4())
        self.conn.execute(
            """
            INSERT INTO jobs(
              job_id, job_type, payload_json, status, attempts, run_after, lease_until, leased_by, updated_at
            )
            VALUES (?, 'embed_chunk', ?, 'pending', 0, NULL, NULL, NULL, ?)
            """,
            (job_id, json.dumps({"chunk_id": chunk_id}), _utc_iso()),
        )
        return True

    def _refresh_conversation_summary(self, *, conversation_id: str, project_id: str) -> None:
        rows = self.conn.execute(
            """
            SELECT role, content, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (conversation_id,),
        ).fetchall()

        if not rows:
            self.conn.execute(
                "DELETE FROM conversation_summaries WHERE conversation_id = ?",
                (conversation_id,),
            )
            return

        role_counts: Counter[str] = Counter()
        cleaned_messages: list[tuple[str, str]] = []
        for row in rows:
            role = str(row["role"])
            role_counts[role] += 1
            cleaned = _clean_message_content(str(row["content"]))
            if cleaned:
                cleaned_messages.append((role, cleaned))

        first_user = next((text for role, text in cleaned_messages if role == "user"), "")
        last_assistant = next(
            (text for role, text in reversed(cleaned_messages) if role == "assistant"),
            "",
        )
        recent = cleaned_messages[-6:]

        lines = [
            f"Conversation {conversation_id}",
            (
                "Messages: "
                f"{len(rows)} (user={role_counts.get('user', 0)}, "
                f"assistant={role_counts.get('assistant', 0)}, "
                f"tool={role_counts.get('tool', 0)}, "
                f"system={role_counts.get('system', 0)})"
            ),
        ]
        if first_user:
            lines.append(f"Initial request: {_snippet(first_user, 220)}")
        if last_assistant:
            lines.append(f"Latest assistant response: {_snippet(last_assistant, 220)}")
        if recent:
            lines.append("Recent turns:")
            for role, text in recent:
                lines.append(f"- [{role}] {_snippet(text, 200)}")

        summary_text = "\n".join(lines)
        now = _utc_iso()
        self.conn.execute(
            """
            INSERT INTO conversation_summaries(
              conversation_id, project_id, summary_text, message_count, summarizer_version, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id)
            DO UPDATE SET
              project_id = excluded.project_id,
              summary_text = excluded.summary_text,
              message_count = excluded.message_count,
              summarizer_version = excluded.summarizer_version,
              updated_at = excluded.updated_at
            """,
            (
                conversation_id,
                project_id,
                summary_text,
                len(rows),
                self.settings.memory_summarizer_version,
                now,
            ),
        )

    def _lexical_candidates(self, *, project_id: str, query: str, top_k: int) -> list[RankedCandidate]:
        fts_query = to_fts_query(query)
        if not fts_query:
            return []

        rows = self.conn.execute(
            """
            SELECT
              c.chunk_id,
              c.chunk_text,
              c.chunk_type,
              c.conversation_id,
              c.created_at,
              c.importance,
              bm25(chunks_fts) AS bm25_score
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
              AND c.project_id = ?
              AND c.archived = 0
            ORDER BY bm25_score
            LIMIT ?
            """,
            (fts_query, project_id, top_k),
        ).fetchall()

        return [
            RankedCandidate(
                chunk_id=row["chunk_id"],
                chunk_text=row["chunk_text"],
                chunk_type=row["chunk_type"],
                conversation_id=row["conversation_id"],
                created_at=row["created_at"],
                importance=float(row["importance"]),
                score=0.0,
            )
            for row in rows
        ]

    def _dense_candidates(self, *, project_id: str, query: str, top_k: int) -> list[RankedCandidate]:
        if self.vector_index is not None:
            qdrant_candidates = self._dense_candidates_qdrant(project_id=project_id, query=query, top_k=top_k)
            if qdrant_candidates:
                return qdrant_candidates
        try:
            q_vec = self.embedding_provider.embed([query])[0]
        except Exception:  # noqa: BLE001
            return []

        return self._dense_candidates_sqlite(project_id=project_id, q_vec=q_vec, top_k=top_k)

    def _dense_candidates_sqlite(
        self,
        *,
        project_id: str,
        q_vec: list[float],
        top_k: int,
    ) -> list[RankedCandidate]:
        rows = self.conn.execute(
            """
            SELECT
              c.chunk_id,
              c.chunk_text,
              c.chunk_type,
              c.conversation_id,
              c.created_at,
              c.importance,
              e.vector_json
            FROM chunk_embeddings e
            JOIN chunks c ON c.chunk_id = e.chunk_id
            WHERE c.project_id = ?
              AND c.archived = 0
              AND e.embed_model = ?
              AND e.embed_dim = ?
              AND e.distance_metric = ?
            ORDER BY c.created_at DESC
            LIMIT 10000
            """,
            (
                project_id,
                self.embedding_provider.model,
                self.settings.memory_embedding_dimensions,
                self.settings.memory_embed_distance_metric,
            ),
        ).fetchall()

        scored: list[tuple[float, RankedCandidate]] = []
        for row in rows:
            try:
                vec = [float(v) for v in json.loads(row["vector_json"])]
            except Exception:  # noqa: BLE001
                continue
            score = cosine_similarity(q_vec, vec)
            candidate = RankedCandidate(
                chunk_id=row["chunk_id"],
                chunk_text=row["chunk_text"],
                chunk_type=row["chunk_type"],
                conversation_id=row["conversation_id"],
                created_at=row["created_at"],
                importance=float(row["importance"]),
                score=score,
            )
            scored.append((score, candidate))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [candidate for _, candidate in scored[:top_k]]

    def _dense_candidates_qdrant(
        self, *, project_id: str, query: str, top_k: int
    ) -> list[RankedCandidate]:
        if self.vector_index is None:
            return []
        try:
            q_vec = self.embedding_provider.embed([query])[0]
            points = self.vector_index.query_points(vector=q_vec, project_id=project_id, limit=top_k)
        except Exception as exc:  # noqa: BLE001
            self.vector_index_error = str(exc)
            self.metrics.inc("qdrant_query_errors")
            return []

        if not points:
            return []

        ordered_chunk_ids: list[str] = []
        score_by_chunk: dict[str, float] = {}
        for point in points:
            if not isinstance(point, dict):
                continue
            point_id = point.get("id")
            if point_id is None:
                continue
            chunk_id = str(point_id)
            ordered_chunk_ids.append(chunk_id)
            score_by_chunk[chunk_id] = _qdrant_score_to_similarity(
                score=point.get("score"),
                distance_metric=self.settings.memory_embed_distance_metric,
            )
        if not ordered_chunk_ids:
            return []

        placeholders = ",".join("?" for _ in ordered_chunk_ids)
        rows = self.conn.execute(
            f"""
            SELECT chunk_id, chunk_text, chunk_type, conversation_id, created_at, importance
            FROM chunks
            WHERE project_id = ?
              AND archived = 0
              AND chunk_id IN ({placeholders})
            """,
            (project_id, *ordered_chunk_ids),
        ).fetchall()
        row_by_chunk = {str(row["chunk_id"]): row for row in rows}

        ranked: list[RankedCandidate] = []
        for chunk_id in ordered_chunk_ids:
            row = row_by_chunk.get(chunk_id)
            if row is None:
                continue
            ranked.append(
                RankedCandidate(
                    chunk_id=chunk_id,
                    chunk_text=row["chunk_text"],
                    chunk_type=row["chunk_type"],
                    conversation_id=row["conversation_id"],
                    created_at=row["created_at"],
                    importance=float(row["importance"]),
                    score=float(score_by_chunk.get(chunk_id, 0.0)),
                )
            )
        return ranked[:top_k]

    def _build_embedding_provider(self) -> EmbeddingProvider:
        provider = self.settings.memory_embedding_provider.lower().strip()
        if provider == "ollama":
            return OllamaEmbeddingProvider(
                model=self.settings.memory_embedding_model,
                base_url=self.settings.memory_ollama_base_url,
                dimensions=self.settings.memory_embedding_dimensions,
            )
        if provider == "tei":
            return TEIEmbeddingProvider(
                model=self.settings.memory_embedding_model,
                base_url=self.settings.memory_tei_base_url,
                dimensions=self.settings.memory_embedding_dimensions,
            )
        if provider in {"openai", "openai_compat"}:
            return OpenAICompatEmbeddingProvider(
                model=self.settings.memory_embedding_model,
                base_url=self.settings.memory_openai_base_url,
                api_key=self.settings.memory_openai_api_key,
                dimensions=self.settings.memory_embedding_dimensions,
            )
        return MockEmbeddingProvider(
            model="mock-embed",
            dimensions=self.settings.memory_embedding_dimensions,
        )

    def _build_vector_index(self) -> QdrantVectorIndex | None:
        if self.retrieval_backend != "qdrant":
            return None
        index = QdrantVectorIndex(
            base_url=self.settings.memory_qdrant_url,
            collection=self.settings.memory_qdrant_collection,
            dimensions=self.settings.memory_embedding_dimensions,
            distance_metric=self.settings.memory_embed_distance_metric,
            api_key=self.settings.memory_qdrant_api_key,
            timeout_seconds=self.settings.memory_qdrant_timeout_seconds,
        )
        ok, detail = index.health()
        if not ok:
            self.vector_index_error = f"qdrant not healthy: {detail}"
            return None
        try:
            index.ensure_collection()
        except Exception as exc:  # noqa: BLE001
            self.vector_index_error = f"qdrant collection init failed: {exc}"
            return None
        self.vector_index_error = None
        return index

    def _is_denied_transcript_path(self, transcript_path: str) -> bool:
        normalized = transcript_path.lower()
        return any(pattern in normalized for pattern in self.settings.denylist_patterns)


class _SessionGuard:
    def __init__(self, service: MemoryService) -> None:
        self.service = service

    def __enter__(self) -> "_SessionGuard":
        self.service._session_enter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> bool:
        self.service._session_exit()
        return False


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _chunk_hash(project_id: str, conversation_id: str, chunk_type: str, chunk_text: str) -> str:
    payload = f"{project_id}|{conversation_id}|{chunk_type}|{chunk_text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


_UUID_LINE_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_TOOL_TAG_RE = re.compile(r"</?(tool_use_error|thinking|analysis|reasoning)>", re.IGNORECASE)
_TOOL_LIKE_DIRECTIVE_RE = re.compile(r"^\s*::[a-z0-9_-]+(?:\{|$)", re.IGNORECASE)
_NOISE_KEYS = {
    "tool_name",
    "tool_call_id",
    "internal_agent_id",
    "trace_id",
    "request_id",
    "sandbox",
}


def _clean_message_content(text: str) -> str:
    normalized = _TOOL_TAG_RE.sub("", text.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if not normalized:
        return ""

    cleaned_lines: list[str] = []
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower in {"true", "false", "none", "null"}:
            continue
        if _UUID_LINE_RE.match(line):
            continue
        if line.startswith("/Users/") and " " not in line:
            continue
        if line.startswith("{") and line.endswith("}") and len(line) > 120:
            try:
                parsed = json.loads(line)
            except Exception:  # noqa: BLE001
                pass
            else:
                if isinstance(parsed, dict) and _NOISE_KEYS.intersection(parsed.keys()):
                    continue
        cleaned_lines.append(line)

    if not cleaned_lines:
        return ""
    compact = "\n".join(cleaned_lines)
    return compact[:20000]


def _safe_render_memory_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    safe_lines: list[str] = []
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if _TOOL_LIKE_DIRECTIVE_RE.match(line):
            safe_lines.append("\\" + line)
            continue
        if line.startswith("```"):
            safe_lines.append("'''")
            continue
        safe_lines.append(line)
    if not safe_lines:
        return ""
    return "\n".join(safe_lines)[:20000]


def _snippet(text: str, limit: int = 320) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _request_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _path_mtime_iso(path_value: str) -> str | None:
    if not path_value:
        return None
    try:
        stat = Path(path_value).stat()
    except OSError:
        return None
    return datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(timespec="seconds")


def _source_hash(
    *,
    source_path: str | None,
    source_url: str | None,
    conversation_id: str,
    source_anchor: str,
    chunk_index: int,
) -> str:
    payload = "|".join(
        [
            source_path or "",
            source_url or "",
            conversation_id,
            source_anchor,
            str(chunk_index),
        ]
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _infer_trust_level(*, source_path: str | None, source_url: str | None) -> str:
    if source_path in {"memory_facts", "compaction"}:
        return "derived"
    if source_url:
        return "external"
    return "untrusted"


def _clamp_vote(value: object) -> float:
    if value is None:
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(-1.0, min(1.0, parsed))


def _round_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _qdrant_score_to_similarity(*, score: object, distance_metric: str) -> float:
    try:
        parsed = float(score)
    except (TypeError, ValueError):
        return 0.0
    metric = (distance_metric or "cosine").strip().lower()
    if metric in {"euclid", "euclidean", "l2", "manhattan", "l1"}:
        return -parsed
    return parsed


def _ms(seconds: float) -> float:
    return round(seconds * 1000.0, 3)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 3)
    idx = max(0, min(len(values) - 1, int(round((len(values) - 1) * p))))
    return round(values[idx], 3)


def _fact_conversation_id(project_id: str) -> str:
    return "facts-" + hashlib.sha1(project_id.encode("utf-8")).hexdigest()[:16]


def _fact_chunk_id(fact_id: str) -> str:
    return f"fact-{fact_id}"
