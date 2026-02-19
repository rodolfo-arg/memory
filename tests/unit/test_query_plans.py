from __future__ import annotations

from app.api.schemas import IngestMessageRequest
from app.config import get_settings
from app.service import MemoryService


def test_query_plans_and_indexes(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MEMORY_DB_PATH", str(db_path))
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("MEMORY_EMBEDDING_DIMENSIONS", "128")
    monkeypatch.setenv("MEMORY_EMBED_DISTANCE_METRIC", "cosine")
    get_settings.cache_clear()

    service = MemoryService(get_settings())
    try:
        service.ingest_message(
            IngestMessageRequest(
                project_id="memory",
                conversation_id="plan-conv",
                role="assistant",
                content="Use pnpm prisma migrate deploy for migrations.",
            )
        )
        service.embed_pending(batch_size=50)

        with service.lock:
            lexical_plan_rows = service.conn.execute(
                """
                EXPLAIN QUERY PLAN
                SELECT c.chunk_id
                FROM chunks_fts
                JOIN chunks c ON c.id = chunks_fts.rowid
                WHERE chunks_fts MATCH ?
                  AND c.project_id = ?
                  AND c.archived = 0
                ORDER BY bm25(chunks_fts)
                LIMIT 10
                """,
                ('"migrate"', "memory"),
            ).fetchall()
            lexical_plan = " | ".join(str(row["detail"]).lower() for row in lexical_plan_rows)
            assert "chunks_fts" in lexical_plan
            assert "virtual table index" in lexical_plan

            dense_plan_rows = service.conn.execute(
                """
                EXPLAIN QUERY PLAN
                SELECT c.chunk_id
                FROM chunk_embeddings e
                JOIN chunks c ON c.chunk_id = e.chunk_id
                WHERE c.project_id = ?
                  AND c.archived = 0
                  AND e.embed_model = ?
                  AND e.embed_dim = ?
                  AND e.distance_metric = ?
                ORDER BY c.created_at DESC
                LIMIT 100
                """,
                (
                    "memory",
                    service.embedding_provider.model,
                    service.settings.memory_embedding_dimensions,
                    service.settings.memory_embed_distance_metric,
                ),
            ).fetchall()
            dense_plan = " | ".join(str(row["detail"]).lower() for row in dense_plan_rows)
            assert "idx_chunk_embeddings_lookup" in dense_plan

            chunk_indexes = {
                str(row["name"])
                for row in service.conn.execute("PRAGMA index_list('chunks')").fetchall()
            }
            assert "idx_chunks_source_slot" in chunk_indexes
    finally:
        service.close()
        get_settings.cache_clear()
