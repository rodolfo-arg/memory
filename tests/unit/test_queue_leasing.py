from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.api.schemas import IngestMessageRequest
from app.config import get_settings
from app.db import connect
from app.service import MemoryService


def _build_service(tmp_path: Path, monkeypatch) -> tuple[MemoryService, Path]:
    db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MEMORY_DB_PATH", str(db_path))
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("MEMORY_EMBEDDING_DIMENSIONS", "128")
    monkeypatch.setenv("MEMORY_EMBED_JOB_LEASE_SECONDS", "30")
    get_settings.cache_clear()
    service = MemoryService(get_settings())
    return service, db_path


def test_enqueued_jobs_start_pending(tmp_path: Path, monkeypatch) -> None:
    service, db_path = _build_service(tmp_path, monkeypatch)
    try:
        service.ingest_message(
            IngestMessageRequest(
                project_id="memory",
                conversation_id="conv-pending",
                role="assistant",
                content="Use pnpm prisma migrate deploy",
            )
        )
        conn = connect(db_path)
        try:
            statuses = {
                str(row["status"])
                for row in conn.execute(
                    "SELECT status FROM jobs WHERE job_type='embed_chunk'"
                ).fetchall()
            }
        finally:
            conn.close()
        assert "pending" in statuses
        assert "queued" not in statuses
    finally:
        service.close()
        get_settings.cache_clear()


def test_embed_pending_reclaims_expired_running_lease(tmp_path: Path, monkeypatch) -> None:
    service, db_path = _build_service(tmp_path, monkeypatch)
    try:
        service.ingest_message(
            IngestMessageRequest(
                project_id="memory",
                conversation_id="conv-lease",
                role="assistant",
                content="Keep lease recovery robust",
            )
        )
        conn = connect(db_path)
        try:
            stale_lease = (datetime.now(UTC) - timedelta(minutes=5)).isoformat(timespec="seconds")
            conn.execute(
                """
                UPDATE jobs
                SET status='running', lease_until=?, leased_by='dead-worker', attempts=1
                WHERE job_type='embed_chunk'
                """,
                (stale_lease,),
            )
            conn.commit()
        finally:
            conn.close()

        result = service.embed_pending(batch_size=32)
        assert result.completed_jobs >= 1

        conn = connect(db_path)
        try:
            done_rows = conn.execute(
                """
                SELECT status, lease_until, leased_by
                FROM jobs
                WHERE job_type='embed_chunk'
                """
            ).fetchall()
        finally:
            conn.close()
        assert done_rows
        assert all(str(row["status"]) == "done" for row in done_rows)
        assert all(row["lease_until"] is None for row in done_rows)
        assert all(row["leased_by"] is None for row in done_rows)
    finally:
        service.close()
        get_settings.cache_clear()
