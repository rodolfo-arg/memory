from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from typing import Callable, TypeVar

from fastapi import FastAPI, Header
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.schemas import (
    AdminCheckpointRequest,
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
    EmbedRequest,
    EmbedResponse,
    HealthResponse,
    IngestBatchResponse,
    IngestMessageRequest,
    IngestMessagesBatchRequest,
    IngestResponse,
    IngestTranscriptRequest,
    LatestMemoryResponse,
    MemoryGraphResponse,
    QueryBatchRequest,
    QueryBatchResponse,
    QueryRequest,
    QueryResponse,
    UpsertFactRequest,
    UpsertFactResponse,
)
from app.config import get_settings
from app.errors import ApiError
from app.service import MemoryService
from app.ui_graph import render_memory_graph_html

T = TypeVar("T")


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    settings = get_settings()
    fastapi_app.state.settings = settings
    fastapi_app.state.memory_service = MemoryService(settings)
    try:
        yield
    finally:
        service: MemoryService | None = getattr(fastapi_app.state, "memory_service", None)
        if service is not None:
            service.close()


app = FastAPI(title="Claude Local Memory API", version="0.2.0", lifespan=lifespan)
_static_dir = Path(__file__).resolve().parent / "static"
if _static_dir.exists():
    app.mount("/ui/static", StaticFiles(directory=_static_dir), name="ui-static")


def _service() -> MemoryService:
    service: MemoryService | None = getattr(app.state, "memory_service", None)
    if service is None:
        raise ApiError(
            code="INTERNAL_ERROR",
            message="service not initialized",
            status_code=500,
            retryable=True,
        )
    return service


def _execute(endpoint: str, fn: Callable[[], T]) -> T | JSONResponse:
    started = perf_counter()
    try:
        return fn()
    except ApiError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())
    except sqlite3.OperationalError as exc:
        text = str(exc)
        if "locked" in text.lower():
            err = ApiError(
                code="DB_LOCKED_RETRYABLE",
                message=text,
                status_code=503,
                retryable=True,
                hint="retry with exponential backoff",
            )
            return JSONResponse(status_code=err.status_code, content=err.to_payload())
        err = ApiError(code="INTERNAL_ERROR", message=text, status_code=500, retryable=False)
        return JSONResponse(status_code=err.status_code, content=err.to_payload())
    except Exception as exc:  # noqa: BLE001
        err = ApiError(
            code="INTERNAL_ERROR",
            message=str(exc),
            status_code=500,
            retryable=False,
        )
        return JSONResponse(status_code=err.status_code, content=err.to_payload())
    finally:
        try:
            _service().record_endpoint_latency(endpoint, (perf_counter() - started) * 1000.0)
        except Exception:  # noqa: BLE001
            pass


def _require_admin_token(provided: str | None) -> None:
    expected = _service().settings.memory_admin_token.strip()
    if not expected:
        return
    if provided != expected:
        raise ApiError(
            code="UNAUTHORIZED",
            message="invalid admin token",
            status_code=401,
            retryable=False,
            hint="provide X-Admin-Token",
        )


@app.get("/v1/health", response_model=HealthResponse)
def health():
    return _execute("GET /v1/health", lambda: _service().health())


@app.get("/v1/metrics", response_class=PlainTextResponse)
def metrics():
    return _execute("GET /v1/metrics", lambda: _service().metrics_text())


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/v1/memory/bootstrap", response_model=BootstrapResponse)
def bootstrap(project_id: str, token_budget: int = 600, k: int = 6):
    return _execute(
        "GET /v1/memory/bootstrap",
        lambda: _service().bootstrap_memory(project_id=project_id, token_budget=token_budget, k=k),
    )


@app.get("/v1/memory/latest", response_model=LatestMemoryResponse)
def latest_memory(
    project_id: str,
    conversation_id: str | None = None,
    limit: int = 5,
    include_chunks: bool = True,
    include_facts: bool = True,
):
    return _execute(
        "GET /v1/memory/latest",
        lambda: _service().latest_memory(
            project_id=project_id,
            conversation_id=conversation_id,
            limit=limit,
            include_chunks=include_chunks,
            include_facts=include_facts,
        ),
    )


@app.get("/v1/memory/conversation/{conversation_id}", response_model=ConversationMemoryResponse)
def memory_conversation(
    conversation_id: str,
    project_id: str | None = None,
    limit: int = 2000,
    offset: int = 0,
    include_raw: bool = False,
):
    return _execute(
        "GET /v1/memory/conversation/{conversation_id}",
        lambda: _service().conversation_memory(
            conversation_id=conversation_id,
            project_id=project_id,
            limit=limit,
            offset=offset,
            include_raw=include_raw,
        ),
    )


@app.post("/v1/memory/ingest/transcript", response_model=IngestResponse)
def ingest_transcript(req: IngestTranscriptRequest):
    return _execute("POST /v1/memory/ingest/transcript", lambda: _service().ingest_transcript(req))


@app.post("/v1/memory/ingest/message", response_model=IngestResponse)
def ingest_message(req: IngestMessageRequest):
    return _execute("POST /v1/memory/ingest/message", lambda: _service().ingest_message(req))


@app.post("/v1/memory/ingest/messages/batch", response_model=IngestBatchResponse)
def ingest_messages_batch(
    req: IngestMessagesBatchRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return _execute(
        "POST /v1/memory/ingest/messages/batch",
        lambda: _service().ingest_messages_batch(req, idempotency_key=idempotency_key),
    )


@app.post("/v1/memory/ingest/chunks/embed", response_model=EmbedResponse)
def embed_chunks(req: EmbedRequest):
    return _execute("POST /v1/memory/ingest/chunks/embed", lambda: _service().embed_pending(req.batch_size))


@app.post("/v1/memory/query", response_model=QueryResponse)
def query(req: QueryRequest):
    return _execute("POST /v1/memory/query", lambda: _service().query_memory(req))


@app.post("/v1/memory/query/batch", response_model=QueryBatchResponse)
def query_batch(req: QueryBatchRequest):
    return _execute("POST /v1/memory/query/batch", lambda: _service().query_memory_batch(req))


@app.get("/v1/memory/graph", response_model=MemoryGraphResponse)
def memory_graph(
    project_id: str,
    include_archived: bool = False,
    max_conversations: int = 220,
    max_chunks: int = 2400,
    max_facts: int = 1200,
):
    return _execute(
        "GET /v1/memory/graph",
        lambda: _service().memory_graph(
            project_id=project_id,
            include_archived=include_archived,
            max_conversations=max_conversations,
            max_chunks=max_chunks,
            max_facts=max_facts,
        ),
    )


@app.get("/ui/memory/graph", response_class=HTMLResponse)
def memory_graph_ui(project_id: str = ""):
    return HTMLResponse(content=render_memory_graph_html(default_project_id=project_id))


@app.post("/v1/memory/facts/upsert", response_model=UpsertFactResponse)
def upsert_fact(req: UpsertFactRequest):
    return _execute("POST /v1/memory/facts/upsert", lambda: _service().upsert_fact(req))


@app.post("/v1/memory/chunks/feedback", response_model=ChunkFeedbackResponse)
def chunk_feedback(req: ChunkFeedbackRequest):
    return _execute("POST /v1/memory/chunks/feedback", lambda: _service().record_chunk_feedback(req))


@app.post("/v1/memory/compact", response_model=CompactResponse)
@app.post("/v1/memory/maintain/compact", response_model=CompactResponse)
def compact(req: CompactRequest):
    return _execute("POST /v1/memory/compact", lambda: _service().compact(req))


@app.post("/v1/admin/reembed", response_model=AdminReembedResponse)
def admin_reembed(
    req: AdminReembedRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    def _run() -> AdminReembedResponse:
        _require_admin_token(x_admin_token)
        return _service().admin_reembed(req)

    return _execute("POST /v1/admin/reembed", _run)


@app.post("/v1/admin/resummarize", response_model=AdminResummarizeResponse)
def admin_resummarize(
    req: AdminResummarizeRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    def _run() -> AdminResummarizeResponse:
        _require_admin_token(x_admin_token)
        return _service().admin_resummarize(req)

    return _execute("POST /v1/admin/resummarize", _run)


@app.get("/v1/admin/stats", response_model=AdminStatsResponse)
def admin_stats(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    def _run() -> AdminStatsResponse:
        _require_admin_token(x_admin_token)
        return _service().admin_stats()

    return _execute("GET /v1/admin/stats", _run)


@app.post("/v1/admin/checkpoint", response_model=AdminCheckpointResponse)
def admin_checkpoint(
    req: AdminCheckpointRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    def _run() -> AdminCheckpointResponse:
        _require_admin_token(x_admin_token)
        return _service().admin_checkpoint(req.mode)

    return _execute("POST /v1/admin/checkpoint", _run)


@app.post("/v1/admin/vacuum", response_model=AdminVacuumResponse)
def admin_vacuum(
    req: AdminVacuumRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    def _run() -> AdminVacuumResponse:
        _require_admin_token(x_admin_token)
        return _service().admin_vacuum(req)

    return _execute("POST /v1/admin/vacuum", _run)
