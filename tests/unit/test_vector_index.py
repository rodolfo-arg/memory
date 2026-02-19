from __future__ import annotations

import httpx

from app.domain.vector_index import QdrantVectorIndex, _qdrant_distance


class _FakeQdrantClient:
    def __init__(self, routes: dict[tuple[str, str], httpx.Response]) -> None:
        self._routes = routes

    def __enter__(self) -> "_FakeQdrantClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False

    def get(self, url: str, headers: dict[str, str] | None = None):
        _ = headers
        return self._routes[("GET", url)]

    def post(self, url: str, json: dict[str, object] | None = None, headers: dict[str, str] | None = None):
        _ = json
        _ = headers
        return self._routes[("POST", url)]

    def put(
        self,
        url: str,
        json: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ):
        _ = json
        _ = params
        _ = headers
        return self._routes[("PUT", url)]


def _response(method: str, url: str, status: int, payload: object) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json=payload,
        request=httpx.Request(method, url),
    )


def test_qdrant_distance_mapping() -> None:
    assert _qdrant_distance("cosine") == "Cosine"
    assert _qdrant_distance("dot") == "Dot"
    assert _qdrant_distance("euclidean") == "Euclid"
    assert _qdrant_distance("manhattan") == "Manhattan"


def test_qdrant_collection_create_and_query(monkeypatch) -> None:
    base = "http://127.0.0.1:6333"
    collection = "memory_chunks"
    routes = {
        ("GET", f"{base}/collections/{collection}"): _response(
            "GET",
            f"{base}/collections/{collection}",
            404,
            {"status": "error"},
        ),
        ("PUT", f"{base}/collections/{collection}"): _response(
            "PUT",
            f"{base}/collections/{collection}",
            200,
            {"status": "ok"},
        ),
        ("POST", f"{base}/collections/{collection}/points/query"): _response(
            "POST",
            f"{base}/collections/{collection}/points/query",
            200,
            {
                "status": "ok",
                "result": {
                    "points": [
                        {"id": "chunk-1", "score": 0.9},
                        {"id": "chunk-2", "score": 0.8},
                    ]
                },
            },
        ),
    }
    monkeypatch.setattr("app.domain.vector_index.httpx.Client", lambda timeout: _FakeQdrantClient(routes))

    index = QdrantVectorIndex(
        base_url=base,
        collection=collection,
        dimensions=128,
        distance_metric="cosine",
    )
    points = index.query_points(vector=[0.1, 0.2], project_id="memory", limit=2)

    assert [point["id"] for point in points] == ["chunk-1", "chunk-2"]
