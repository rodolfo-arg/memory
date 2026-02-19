from __future__ import annotations

from dataclasses import dataclass

import httpx


class VectorIndexError(RuntimeError):
    pass


@dataclass
class QdrantVectorIndex:
    base_url: str
    collection: str
    dimensions: int
    distance_metric: str
    api_key: str = ""
    timeout_seconds: float = 2.5

    _collection_ready: bool = False

    def health(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=min(2.0, self.timeout_seconds)) as client:
                response = client.get(
                    f"{self.base_url.rstrip('/')}/readyz",
                    headers=self._headers(),
                )
                if response.status_code == 404:
                    response = client.get(
                        f"{self.base_url.rstrip('/')}/healthz",
                        headers=self._headers(),
                    )
                response.raise_for_status()
            return True, "ok"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    def ensure_collection(self) -> None:
        if self._collection_ready:
            return

        base = self.base_url.rstrip("/")
        headers = self._headers()
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(f"{base}/collections/{self.collection}", headers=headers)
            if response.status_code == 404:
                create_payload = {
                    "vectors": {
                        "size": int(self.dimensions),
                        "distance": _qdrant_distance(self.distance_metric),
                    }
                }
                create = client.put(
                    f"{base}/collections/{self.collection}",
                    json=create_payload,
                    headers=headers,
                )
                create.raise_for_status()
                self._collection_ready = True
                return
            response.raise_for_status()
            self._collection_ready = True

    def upsert_points(self, points: list[dict[str, object]]) -> None:
        if not points:
            return
        self.ensure_collection()
        base = self.base_url.rstrip("/")
        body = {"points": points}
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.put(
                f"{base}/collections/{self.collection}/points",
                params={"wait": "false"},
                json=body,
                headers=self._headers(),
            )
            response.raise_for_status()

    def query_points(self, *, vector: list[float], project_id: str, limit: int) -> list[dict[str, object]]:
        self.ensure_collection()
        base = self.base_url.rstrip("/")
        body = {
            "query": vector,
            "limit": int(max(1, limit)),
            "with_payload": True,
            "filter": {
                "must": [
                    {"key": "project_id", "match": {"value": project_id}},
                    {"key": "archived", "match": {"value": 0}},
                ]
            },
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{base}/collections/{self.collection}/points/query",
                json=body,
                headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()
        result = data.get("result")
        if isinstance(result, dict) and isinstance(result.get("points"), list):
            return result["points"]
        if isinstance(result, list):
            return result
        raise VectorIndexError("qdrant query response missing points")

    def _headers(self) -> dict[str, str]:
        token = self.api_key.strip()
        if not token:
            return {}
        return {"api-key": token}


def _qdrant_distance(distance_metric: str) -> str:
    key = (distance_metric or "cosine").strip().lower()
    if key in {"cos", "cosine"}:
        return "Cosine"
    if key in {"dot", "dotproduct"}:
        return "Dot"
    if key in {"euclid", "euclidean", "l2"}:
        return "Euclid"
    if key in {"manhattan", "l1"}:
        return "Manhattan"
    return "Cosine"
