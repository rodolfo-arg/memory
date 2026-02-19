from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import httpx


class EmbeddingError(RuntimeError):
    pass


class EmbeddingProvider:
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def health(self) -> tuple[bool, str]:
        raise NotImplementedError


@dataclass
class MockEmbeddingProvider(EmbeddingProvider):
    model: str = "mock-embed"
    dimensions: int = 384

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vectors.append(self._text_to_vector(text))
        return vectors

    def _text_to_vector(self, text: str) -> list[float]:
        values: list[float] = []
        seed = text.encode("utf-8")
        counter = 0
        while len(values) < self.dimensions:
            digest = hashlib.blake2b(seed + counter.to_bytes(4, "big"), digest_size=32).digest()
            counter += 1
            for i in range(0, len(digest), 4):
                chunk = digest[i : i + 4]
                num = int.from_bytes(chunk, "big", signed=False)
                val = (num / 2**31) - 1.0
                values.append(val)
                if len(values) == self.dimensions:
                    break
        return _l2_normalize(values)

    def health(self) -> tuple[bool, str]:
        return True, "mock provider"


@dataclass
class OllamaEmbeddingProvider(EmbeddingProvider):
    model: str
    base_url: str
    dimensions: int | None = None
    timeout_seconds: float = 8.0

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        payload: dict[str, object] = {
            "model": self.model,
            "input": texts,
            "truncate": True,
        }
        if self.dimensions:
            payload["dimensions"] = self.dimensions

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(f"{self.base_url}/api/embed", json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(f"ollama embed request failed: {exc}") from exc

        if isinstance(data, dict) and isinstance(data.get("embeddings"), list):
            vectors = data["embeddings"]
        elif isinstance(data, dict) and isinstance(data.get("embedding"), list):
            vectors = [data["embedding"]]
        else:
            raise EmbeddingError("ollama response missing embedding data")

        if len(vectors) != len(texts):
            raise EmbeddingError("embedding response length mismatch")

        return [_l2_normalize([float(v) for v in vector]) for vector in vectors]

    def health(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=1.5) as client:
                response = client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            return True, "ok"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)


@dataclass
class TEIEmbeddingProvider(EmbeddingProvider):
    model: str
    base_url: str
    dimensions: int | None = None
    timeout_seconds: float = 8.0

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        with httpx.Client(timeout=self.timeout_seconds) as client:
            # Prefer OpenAI-compatible route when available.
            vectors = self._embed_openai_compat(client, texts)
            if vectors is None:
                vectors = self._embed_native(client, texts)

        if len(vectors) != len(texts):
            raise EmbeddingError("tei response length mismatch")
        return [_l2_normalize([float(v) for v in vector]) for vector in vectors]

    def _embed_openai_compat(
        self, client: httpx.Client, texts: list[str]
    ) -> list[list[float]] | None:
        payload: dict[str, object] = {
            "input": texts,
            "model": self.model,
            "encoding_format": "float",
        }
        if self.dimensions:
            payload["dimensions"] = self.dimensions
        response = client.post(f"{self.base_url.rstrip('/')}/v1/embeddings", json=payload)
        if response.status_code in {404, 405}:
            return None
        response.raise_for_status()
        data = response.json()
        items = data.get("data")
        if not isinstance(items, list):
            raise EmbeddingError("tei /v1/embeddings response missing data")
        ordered = sorted(items, key=lambda item: int(item.get("index", 0)))
        vectors = [item.get("embedding") for item in ordered if isinstance(item, dict)]
        if not all(isinstance(vec, list) for vec in vectors):
            raise EmbeddingError("tei /v1/embeddings invalid embedding payload")
        return vectors

    def _embed_native(self, client: httpx.Client, texts: list[str]) -> list[list[float]]:
        payload: dict[str, object] = {
            "inputs": texts,
            "truncate": True,
            "normalize": True,
        }
        if self.dimensions:
            payload["dimensions"] = self.dimensions
        response = client.post(f"{self.base_url.rstrip('/')}/embed", json=payload)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("embeddings"), list):
            return data["embeddings"]
        raise EmbeddingError("tei /embed response missing embeddings")

    def health(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=1.5) as client:
                response = client.get(f"{self.base_url.rstrip('/')}/health")
                if response.status_code == 404:
                    response = client.get(f"{self.base_url.rstrip('/')}/info")
                response.raise_for_status()
            return True, "ok"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)


@dataclass
class OpenAICompatEmbeddingProvider(EmbeddingProvider):
    model: str
    base_url: str
    api_key: str
    dimensions: int | None = None
    timeout_seconds: float = 12.0

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        token = self.api_key.strip()
        if not token:
            raise EmbeddingError("openai-compatible embedding api key missing")

        payload: dict[str, object] = {
            "model": self.model,
            "input": texts,
            "encoding_format": "float",
        }
        if self.dimensions:
            payload["dimensions"] = self.dimensions
        headers = {"Authorization": f"Bearer {token}"}
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    f"{self.base_url.rstrip('/')}/embeddings", json=payload, headers=headers
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(f"openai-compatible embed request failed: {exc}") from exc

        items = data.get("data")
        if not isinstance(items, list):
            raise EmbeddingError("openai-compatible response missing data")
        ordered = sorted(items, key=lambda item: int(item.get("index", 0)))
        vectors = [item.get("embedding") for item in ordered if isinstance(item, dict)]
        if len(vectors) != len(texts) or not all(isinstance(vec, list) for vec in vectors):
            raise EmbeddingError("openai-compatible response embedding mismatch")
        return [_l2_normalize([float(v) for v in vector]) for vector in vectors]

    def health(self) -> tuple[bool, str]:
        token = self.api_key.strip()
        if not token:
            return False, "missing api key"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            with httpx.Client(timeout=1.8) as client:
                response = client.get(f"{self.base_url.rstrip('/')}/models", headers=headers)
                response.raise_for_status()
            return True, "ok"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]
