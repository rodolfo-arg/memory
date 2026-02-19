from __future__ import annotations

import httpx
import pytest

from app.domain.embeddings import (
    EmbeddingError,
    OpenAICompatEmbeddingProvider,
    TEIEmbeddingProvider,
)


class _FakeClient:
    def __init__(self, routes: dict[tuple[str, str], httpx.Response]) -> None:
        self._routes = routes

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False

    def post(self, url: str, json: dict[str, object] | None = None, headers: dict[str, str] | None = None):
        _ = json
        _ = headers
        key = ("POST", url)
        if key not in self._routes:
            raise AssertionError(f"unexpected POST {url}")
        return self._routes[key]

    def get(self, url: str, headers: dict[str, str] | None = None):
        _ = headers
        key = ("GET", url)
        if key not in self._routes:
            raise AssertionError(f"unexpected GET {url}")
        return self._routes[key]


def _response(method: str, url: str, status: int, payload: object) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json=payload,
        request=httpx.Request(method, url),
    )


def test_tei_provider_prefers_openai_route(monkeypatch) -> None:
    base = "http://tei.local"
    routes = {
        ("POST", f"{base}/v1/embeddings"): _response(
            "POST",
            f"{base}/v1/embeddings",
            200,
            {
                "data": [
                    {"index": 1, "embedding": [0.0, 5.0]},
                    {"index": 0, "embedding": [3.0, 4.0]},
                ]
            },
        )
    }
    monkeypatch.setattr("app.domain.embeddings.httpx.Client", lambda timeout: _FakeClient(routes))
    provider = TEIEmbeddingProvider(model="gte-base", base_url=base, dimensions=2)

    vectors = provider.embed(["first", "second"])

    assert vectors[0] == pytest.approx([0.6, 0.8], rel=1e-5)
    assert vectors[1] == pytest.approx([0.0, 1.0], rel=1e-5)


def test_tei_provider_falls_back_to_embed(monkeypatch) -> None:
    base = "http://tei.local"
    routes = {
        ("POST", f"{base}/v1/embeddings"): _response("POST", f"{base}/v1/embeddings", 404, {"error": "nf"}),
        ("POST", f"{base}/embed"): _response(
            "POST",
            f"{base}/embed",
            200,
            [[1.0, 0.0], [0.0, 2.0]],
        ),
    }
    monkeypatch.setattr("app.domain.embeddings.httpx.Client", lambda timeout: _FakeClient(routes))
    provider = TEIEmbeddingProvider(model="gte-base", base_url=base, dimensions=2)

    vectors = provider.embed(["first", "second"])

    assert vectors[0] == pytest.approx([1.0, 0.0], rel=1e-5)
    assert vectors[1] == pytest.approx([0.0, 1.0], rel=1e-5)


def test_openai_compat_provider_requires_key() -> None:
    provider = OpenAICompatEmbeddingProvider(
        model="text-embedding-3-small",
        base_url="https://api.openai.com/v1",
        api_key="",
    )
    with pytest.raises(EmbeddingError, match="api key"):
        provider.embed(["hello"])


def test_openai_compat_provider_parses_response(monkeypatch) -> None:
    base = "https://api.example.com/v1"
    routes = {
        ("POST", f"{base}/embeddings"): _response(
            "POST",
            f"{base}/embeddings",
            200,
            {
                "data": [
                    {"index": 0, "embedding": [2.0, 0.0]},
                    {"index": 1, "embedding": [0.0, 3.0]},
                ]
            },
        )
    }
    monkeypatch.setattr("app.domain.embeddings.httpx.Client", lambda timeout: _FakeClient(routes))
    provider = OpenAICompatEmbeddingProvider(
        model="text-embedding-3-small",
        base_url=base,
        api_key="sk-test",
    )

    vectors = provider.embed(["a", "b"])

    assert vectors[0] == pytest.approx([1.0, 0.0], rel=1e-5)
    assert vectors[1] == pytest.approx([0.0, 1.0], rel=1e-5)
