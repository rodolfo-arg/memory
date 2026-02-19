from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_ingest_embed_query_loop(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "memory.db"

    monkeypatch.setenv("MEMORY_DB_PATH", str(db_path))
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("MEMORY_EMBEDDING_DIMENSIONS", "128")
    get_settings.cache_clear()

    with TestClient(app) as client:
        ingest = client.post(
            "/v1/memory/ingest/message",
            json={
                "project_id": "memory",
                "conversation_id": "conv-1",
                "role": "assistant",
                "content": "Use `pnpm prisma migrate deploy` to apply migrations.",
            },
        )
        assert ingest.status_code == 200
        assert ingest.json()["chunks_created"] >= 1

        embed = client.post("/v1/memory/ingest/chunks/embed", json={"batch_size": 50})
        assert embed.status_code == 200
        assert embed.json()["completed_jobs"] >= 1

        query = client.post(
            "/v1/memory/query",
            json={
                "project_id": "memory",
                "query": "what command applies migrations",
                "intent": "procedural",
                "k": 5,
                "token_budget": 800,
            },
        )
        assert query.status_code == 200
        payload = query.json()
        assert payload["results"]


def test_transcript_ingest_delta(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "memory.db"
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        '{"role":"user","content":"Need migration command"}\n'
        '{"role":"assistant","content":"Run pnpm prisma migrate deploy"}\n',
        encoding="utf-8",
    )

    monkeypatch.setenv("MEMORY_DB_PATH", str(db_path))
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "mock")
    get_settings.cache_clear()

    with TestClient(app) as client:
        first = client.post(
            "/v1/memory/ingest/transcript",
            json={
                "project_id": "memory",
                "session_id": "sess-1",
                "transcript_path": str(transcript),
                "ingest_mode": "delta",
            },
        )
        assert first.status_code == 200
        assert first.json()["messages_ingested"] == 2

        second = client.post(
            "/v1/memory/ingest/transcript",
            json={
                "project_id": "memory",
                "session_id": "sess-1",
                "transcript_path": str(transcript),
                "ingest_mode": "delta",
            },
        )
        assert second.status_code == 200
        assert second.json()["messages_ingested"] == 0


def test_bootstrap_and_denylist_guard(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "memory.db"
    denied_transcript = tmp_path / ".env.secret.jsonl"
    denied_transcript.write_text(
        '{"role":"assistant","content":"this should be denied"}\n',
        encoding="utf-8",
    )

    monkeypatch.setenv("MEMORY_DB_PATH", str(db_path))
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("MEMORY_DENYLIST_PATHS", ".env")
    get_settings.cache_clear()

    with TestClient(app) as client:
        denied = client.post(
            "/v1/memory/ingest/transcript",
            json={
                "project_id": "memory",
                "session_id": "sess-deny",
                "transcript_path": str(denied_transcript),
                "ingest_mode": "delta",
            },
        )
        assert denied.status_code == 200
        assert denied.json()["accepted"] is False

        client.post(
            "/v1/memory/ingest/message",
            json={
                "project_id": "memory",
                "conversation_id": "conv-bootstrap",
                "role": "assistant",
                "content": "Decision: use hybrid retrieval with RRF.",
            },
        )
        bootstrap = client.get(
            "/v1/memory/bootstrap",
            params={"project_id": "memory", "token_budget": 400, "k": 3},
        )
        assert bootstrap.status_code == 200
        payload = bootstrap.json()
        assert "results" in payload


def test_batch_ingest_idempotency_and_query_batch(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "memory.db"

    monkeypatch.setenv("MEMORY_DB_PATH", str(db_path))
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("MEMORY_EMBEDDING_DIMENSIONS", "128")
    monkeypatch.setenv("MEMORY_INGEST_BATCH_MAX_MESSAGES", "100")
    get_settings.cache_clear()

    with TestClient(app) as client:
        payload = {
            "project_id": "memory",
            "conversation_id": "batch-conv",
            "messages": [
                {"role": "assistant", "content": "Run pnpm prisma migrate deploy"},
                {"role": "assistant", "content": "Decision: keep hybrid retrieval"},
            ],
        }
        first = client.post(
            "/v1/memory/ingest/messages/batch",
            json=payload,
            headers={"Idempotency-Key": "batch-key-1"},
        )
        assert first.status_code == 200
        first_body = first.json()
        assert first_body["idempotency_hit"] is False
        assert first_body["messages_ingested"] == 2

        second = client.post(
            "/v1/memory/ingest/messages/batch",
            json=payload,
            headers={"Idempotency-Key": "batch-key-1"},
        )
        assert second.status_code == 200
        second_body = second.json()
        assert second_body["idempotency_hit"] is True
        assert second_body["messages_ingested"] == first_body["messages_ingested"]

        client.post("/v1/memory/ingest/chunks/embed", json={"batch_size": 50})
        batch_query = client.post(
            "/v1/memory/query/batch",
            json={
                "project_id": "memory",
                "queries": [
                    {"query": "what command applies migrations", "intent": "procedural"},
                    {"query": "what was the decision", "intent": "semantic"},
                ],
            },
        )
        assert batch_query.status_code == 200
        query_payload = batch_query.json()
        assert len(query_payload["results"]) == 2
        assert "duration_ms" in query_payload


def test_admin_endpoints_and_token_guard(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "memory.db"

    monkeypatch.setenv("MEMORY_DB_PATH", str(db_path))
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("MEMORY_ADMIN_TOKEN", "secret-token")
    get_settings.cache_clear()

    with TestClient(app) as client:
        unauthorized = client.get("/v1/admin/stats")
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["code"] == "UNAUTHORIZED"

        client.post(
            "/v1/memory/ingest/message",
            json={
                "project_id": "memory",
                "conversation_id": "admin-conv",
                "role": "assistant",
                "content": "Run pnpm prisma migrate deploy",
            },
        )
        client.post("/v1/memory/ingest/chunks/embed", json={"batch_size": 50})

        stats = client.get("/v1/admin/stats", headers={"X-Admin-Token": "secret-token"})
        assert stats.status_code == 200
        stats_payload = stats.json()
        assert "counts" in stats_payload
        assert "endpoint_latency_ms" in stats_payload

        checkpoint = client.post(
            "/v1/admin/checkpoint",
            headers={"X-Admin-Token": "secret-token"},
            json={"mode": "TRUNCATE"},
        )
        assert checkpoint.status_code == 200
        assert checkpoint.json()["mode"] == "TRUNCATE"

        vacuum = client.post(
            "/v1/admin/vacuum",
            headers={"X-Admin-Token": "secret-token"},
            json={"max_queued_jobs": 999, "analyze": False},
        )
        assert vacuum.status_code == 200
        assert vacuum.json()["accepted"] is True


def test_fact_upsert_becomes_queryable(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "memory.db"

    monkeypatch.setenv("MEMORY_DB_PATH", str(db_path))
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("MEMORY_EMBEDDING_DIMENSIONS", "128")
    get_settings.cache_clear()

    with TestClient(app) as client:
        fact_text = "Tournament V20 top performer is v19_sent900_oracle on port 9006"
        upsert = client.post(
            "/v1/memory/facts/upsert",
            json={
                "project_id": "memory",
                "fact_text": fact_text,
                "confidence": 0.95,
            },
        )
        assert upsert.status_code == 200
        assert upsert.json()["status"] == "active"
        assert upsert.json()["fact_chunk_id"].startswith("fact-")

        query = client.post(
            "/v1/memory/query",
            json={
                "project_id": "memory",
                "query": "v19_sent900_oracle port 9006 top performer",
                "k": 5,
                "token_budget": 1000,
            },
        )
        assert query.status_code == 200
        body = query.json()
        snippets = [item["snippet"].lower() for item in body["results"]]
        assert any("top performer" in s and "9006" in s for s in snippets)

        hyphen_query = client.post(
            "/v1/memory/query",
            json={
                "project_id": "memory",
                "query": "v19-sent900-oracle-9006",
                "k": 5,
                "token_budget": 1000,
            },
        )
        assert hyphen_query.status_code == 200
        hyphen_body = hyphen_query.json()
        hyphen_snippets = [item["snippet"].lower() for item in hyphen_body["results"]]
        assert any("9006" in s for s in hyphen_snippets)


def test_memory_graph_endpoint_and_ui(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "memory.db"

    monkeypatch.setenv("MEMORY_DB_PATH", str(db_path))
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("MEMORY_EMBEDDING_DIMENSIONS", "128")
    get_settings.cache_clear()

    with TestClient(app) as client:
        client.post(
            "/v1/memory/ingest/message",
            json={
                "project_id": "memory",
                "conversation_id": "graph-conv",
                "role": "assistant",
                "content": "Use pnpm prisma migrate deploy",
            },
        )
        client.post(
            "/v1/memory/facts/upsert",
            json={
                "project_id": "memory",
                "fact_text": "Graph test fact for migration command",
                "confidence": 0.9,
            },
        )
        client.post("/v1/memory/ingest/chunks/embed", json={"batch_size": 50})

        graph = client.get(
            "/v1/memory/graph",
            params={
                "project_id": "memory",
                "max_conversations": 50,
                "max_chunks": 200,
                "max_facts": 50,
            },
        )
        assert graph.status_code == 200
        payload = graph.json()
        kinds = [node["data"]["kind"] for node in payload["nodes"]]
        assert "project" in kinds
        assert "conversation" in kinds
        assert "chunk" in kinds
        assert "fact" in kinds
        assert payload["totals"]["edges"] >= 1

        ui = client.get("/ui/memory/graph", params={"project_id": "memory"})
        assert ui.status_code == 200
        assert "force-graph.min.js" in ui.text.lower()
        assert "id=\"livemode\"" in ui.text.lower()
        assert "id=\"rendermode\"" in ui.text.lower()
        assert "id=\"displaymode\"" in ui.text.lower()
        assert "id=\"graphviewbtn\"" in ui.text.lower()
        assert "id=\"listviewbtn\"" in ui.text.lower()


def test_feedback_and_admin_resummarize(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "memory.db"

    monkeypatch.setenv("MEMORY_DB_PATH", str(db_path))
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("MEMORY_EMBEDDING_DIMENSIONS", "128")
    monkeypatch.setenv("MEMORY_ADMIN_TOKEN", "secret-token")
    get_settings.cache_clear()

    with TestClient(app) as client:
        client.post(
            "/v1/memory/ingest/message",
            json={
                "project_id": "memory",
                "conversation_id": "feedback-conv",
                "role": "assistant",
                "content": "Decision: keep retrieval with explainable score logging.",
            },
        )
        client.post("/v1/memory/ingest/chunks/embed", json={"batch_size": 50})

        query = client.post(
            "/v1/memory/query",
            json={
                "project_id": "memory",
                "query": "what decision did we make",
                "k": 5,
                "token_budget": 800,
            },
        )
        assert query.status_code == 200
        payload = query.json()
        assert payload["results"]
        top = payload["results"][0]
        assert top["source"]["trust_level"] in {"untrusted", "derived", "external"}

        feedback = client.post(
            "/v1/memory/chunks/feedback",
            json={"chunk_id": top["chunk_id"], "user_vote": 1.0, "auto_judgement": 0.5},
        )
        assert feedback.status_code == 200
        assert feedback.json()["updated"] is True

        resummarize = client.post(
            "/v1/admin/resummarize",
            headers={"X-Admin-Token": "secret-token"},
            json={"project_id": "memory", "limit": 100},
        )
        assert resummarize.status_code == 200
        summary_payload = resummarize.json()
        assert "queued_jobs" in summary_payload
        assert "skipped_existing" in summary_payload


def test_latest_memory_endpoint(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "memory.db"

    monkeypatch.setenv("MEMORY_DB_PATH", str(db_path))
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("MEMORY_EMBEDDING_DIMENSIONS", "128")
    get_settings.cache_clear()

    with TestClient(app) as client:
        marker_chunk = "latest-memory-marker-chunk"
        marker_chunk_other = "latest-memory-other-conversation"
        marker_fact = "latest-memory-marker-fact"

        client.post(
            "/v1/memory/ingest/message",
            json={
                "project_id": "memory",
                "conversation_id": "latest-conv",
                "role": "assistant",
                "content": f"Run migration command {marker_chunk}",
            },
        )
        client.post(
            "/v1/memory/ingest/message",
            json={
                "project_id": "memory",
                "conversation_id": "latest-conv-other",
                "role": "assistant",
                "content": f"Different thread {marker_chunk_other}",
            },
        )
        client.post(
            "/v1/memory/facts/upsert",
            json={
                "project_id": "memory",
                "fact_text": f"Confirmed latest insight {marker_fact}",
                "confidence": 0.95,
            },
        )

        latest = client.get(
            "/v1/memory/latest",
            params={
                "project_id": "memory",
                "limit": 5,
                "include_chunks": True,
                "include_facts": True,
            },
        )
        assert latest.status_code == 200
        payload = latest.json()
        assert payload["project_id"] == "memory"
        assert payload["items"]
        kinds = {item["kind"] for item in payload["items"]}
        assert "chunk" in kinds
        assert "fact" in kinds
        text_blob = " ".join(item["text"] for item in payload["items"]).lower()
        assert "latest-memory-marker" in text_blob

        latest_conversation = client.get(
            "/v1/memory/latest",
            params={
                "project_id": "memory",
                "conversation_id": "latest-conv",
                "limit": 10,
                "include_chunks": True,
                "include_facts": False,
            },
        )
        assert latest_conversation.status_code == 200
        filtered = latest_conversation.json()
        assert filtered["items"]
        assert all(item["conversation_id"] == "latest-conv" for item in filtered["items"])
        filtered_blob = " ".join(item["text"] for item in filtered["items"]).lower()
        assert "latest-memory-marker-chunk" in filtered_blob
        assert "latest-memory-other-conversation" not in filtered_blob


def test_conversation_memory_endpoint_and_summary(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "memory.db"

    monkeypatch.setenv("MEMORY_DB_PATH", str(db_path))
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("MEMORY_EMBEDDING_DIMENSIONS", "128")
    get_settings.cache_clear()

    with TestClient(app) as client:
        messages = [
            {"role": "system", "content": "False\n/Users/rodolfo/Developer/project-a\n11111111-1111-1111-1111-111111111111"},
            {"role": "user", "content": "Please restart the tournament with 20 agents."},
            {"role": "assistant", "content": "Done. Tournament restarted and health checks are green."},
            {"role": "tool", "content": '{"tool_name":"shell","request_id":"abc","output":"ok"}'},
        ]
        for item in messages:
            response = client.post(
                "/v1/memory/ingest/message",
                json={
                    "project_id": "memory",
                    "conversation_id": "conv-session-1",
                    "role": item["role"],
                    "content": item["content"],
                },
            )
            assert response.status_code == 200

        conversation = client.get(
            "/v1/memory/conversation/conv-session-1",
            params={"project_id": "memory", "limit": 50, "include_raw": True},
        )
        assert conversation.status_code == 200
        payload = conversation.json()
        assert payload["project_id"] == "memory"
        assert payload["conversation_id"] == "conv-session-1"
        assert payload["total_messages"] == 4
        assert payload["summary"] is not None
        assert "Initial request:" in payload["summary"]["summary_text"]
        assert payload["summary"]["message_count"] == 4
        assert [item["role"] for item in payload["messages"]] == ["system", "user", "assistant", "tool"]
        assert all(item["raw_content"] for item in payload["messages"])

        system_clean = payload["messages"][0]["content"]
        assert "False" not in system_clean
        assert "/Users/rodolfo/Developer/project-a" not in system_clean
        assert "11111111-1111-1111-1111-111111111111" not in system_clean
