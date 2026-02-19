from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class RankedCandidate:
    chunk_id: str
    chunk_text: str
    chunk_type: str
    conversation_id: str
    created_at: str
    importance: float
    score: float = 0.0


def to_fts_query(text: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_./]+", text.lower())
    if not tokens:
        return ""
    cleaned = [token.replace('"', "") for token in tokens[:24]]
    return " ".join(f'"{token}"' for token in cleaned)


def rrf_fuse(
    dense: list[RankedCandidate],
    lexical: list[RankedCandidate],
    *,
    intent: str | None,
    dense_weight: float = 1.0,
    lexical_weight: float = 1.0,
    rrf_k: int = 60,
) -> list[RankedCandidate]:
    fused, _ = rrf_fuse_with_debug(
        dense,
        lexical,
        intent=intent,
        dense_weight=dense_weight,
        lexical_weight=lexical_weight,
        rrf_k=rrf_k,
    )
    return fused


def rrf_fuse_with_debug(
    dense: list[RankedCandidate],
    lexical: list[RankedCandidate],
    *,
    intent: str | None,
    dense_weight: float = 1.0,
    lexical_weight: float = 1.0,
    rrf_k: int = 60,
) -> tuple[list[RankedCandidate], dict[str, dict[str, float | int | None]]]:
    merged: dict[str, RankedCandidate] = {}
    dense_rank_by_chunk: dict[str, int] = {}
    lexical_rank_by_chunk: dict[str, int] = {}
    dense_similarity_by_chunk: dict[str, float] = {}
    debug: dict[str, dict[str, float | int | None]] = {}

    def _copy(item: RankedCandidate) -> RankedCandidate:
        return RankedCandidate(
            chunk_id=item.chunk_id,
            chunk_text=item.chunk_text,
            chunk_type=item.chunk_type,
            conversation_id=item.conversation_id,
            created_at=item.created_at,
            importance=item.importance,
            score=0.0,
        )

    for rank, item in enumerate(dense, start=1):
        dense_rank_by_chunk[item.chunk_id] = rank
        dense_similarity_by_chunk[item.chunk_id] = float(item.score)
        candidate = merged.get(item.chunk_id)
        if candidate is None:
            candidate = _copy(item)
            merged[item.chunk_id] = candidate
        dense_rrf = max(0.0, dense_weight) * (1.0 / (rrf_k + rank))
        candidate.score += dense_rrf

    for rank, item in enumerate(lexical, start=1):
        lexical_rank_by_chunk[item.chunk_id] = rank
        candidate = merged.get(item.chunk_id)
        if candidate is None:
            candidate = _copy(item)
            merged[item.chunk_id] = candidate
        lexical_rrf = max(0.0, lexical_weight) * (1.0 / (rrf_k + rank))
        candidate.score += lexical_rrf

    for candidate in merged.values():
        recency_boost = _recency_boost(candidate.created_at)
        importance_boost = 0.10 * max(0.0, min(1.0, candidate.importance))
        chunk_type_boost = _chunk_type_boost(candidate.chunk_type)
        intent_boost = _intent_boost(candidate.chunk_type, intent)
        candidate.score += recency_boost
        candidate.score += importance_boost
        candidate.score += chunk_type_boost
        candidate.score += intent_boost
        dense_rank = dense_rank_by_chunk.get(candidate.chunk_id)
        lexical_rank = lexical_rank_by_chunk.get(candidate.chunk_id)
        dense_rrf = (
            max(0.0, dense_weight) * (1.0 / (rrf_k + dense_rank))
            if dense_rank is not None
            else 0.0
        )
        lexical_rrf = (
            max(0.0, lexical_weight) * (1.0 / (rrf_k + lexical_rank))
            if lexical_rank is not None
            else 0.0
        )
        debug[candidate.chunk_id] = {
            "dense_rank": dense_rank,
            "lexical_rank": lexical_rank,
            "dense_similarity": round(dense_similarity_by_chunk.get(candidate.chunk_id, 0.0), 6),
            "dense_rrf": round(dense_rrf, 6),
            "lexical_rrf": round(lexical_rrf, 6),
            "recency_boost": round(recency_boost, 6),
            "importance_boost": round(importance_boost, 6),
            "chunk_type_boost": round(chunk_type_boost, 6),
            "intent_boost": round(intent_boost, 6),
            "final_score": round(candidate.score, 6),
            "final_rank": None,
        }

    ordered = sorted(merged.values(), key=lambda c: c.score, reverse=True)
    for rank, candidate in enumerate(ordered, start=1):
        payload = debug.get(candidate.chunk_id)
        if payload is not None:
            payload["final_rank"] = rank
            payload["final_score"] = round(candidate.score, 6)

    return ordered, debug


def trim_to_token_budget(candidates: list[RankedCandidate], token_budget: int) -> list[RankedCandidate]:
    if token_budget <= 0:
        return []

    selected: list[RankedCandidate] = []
    used = 0
    for candidate in candidates:
        est_tokens = max(1, len(candidate.chunk_text) // 4)
        if used + est_tokens > token_budget:
            continue
        selected.append(candidate)
        used += est_tokens
    return selected


def _recency_boost(created_at: str) -> float:
    try:
        normalized = created_at.replace("Z", "+00:00")
        then = datetime.fromisoformat(normalized)
        if then.tzinfo is None:
            then = then.replace(tzinfo=UTC)
    except Exception:  # noqa: BLE001
        return 0.0

    days_old = max(0.0, (datetime.now(UTC) - then).total_seconds() / 86400.0)
    return 0.05 * math.exp(-days_old / 30.0)


def _intent_boost(chunk_type: str, intent: str | None) -> float:
    if not intent:
        return 0.0
    intent_key = intent.lower()
    if intent_key in {"procedural", "command"} and chunk_type == "command":
        return 0.08
    if intent_key in {"fact", "semantic"} and chunk_type in {"decision", "summary"}:
        return 0.06
    if intent_key in {"debug", "error"} and chunk_type == "error":
        return 0.08
    return 0.0


def _chunk_type_boost(chunk_type: str) -> float:
    key = (chunk_type or "").strip().lower()
    if key == "fact":
        return 0.10
    if key in {"decision", "summary"}:
        return 0.06
    if key in {"command", "error"}:
        return 0.04
    if key in {"turn", "tool"}:
        return -0.01
    return 0.0
