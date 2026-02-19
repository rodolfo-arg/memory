#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.api.schemas import QueryRequest
from app.config import get_settings
from app.service import MemoryService


def main() -> int:
    parser = argparse.ArgumentParser(description="Run retrieval evaluation against a golden set.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("tests/eval/golden_set.sample.json"),
        help="Path to JSON dataset file",
    )
    parser.add_argument(
        "--dataset-name",
        type=str,
        default="default-golden-set",
        help="Logical name for this dataset",
    )
    parser.add_argument("--k", type=int, default=8, help="Top-k retrieval cutoff")
    args = parser.parse_args()

    cases = _load_cases(args.dataset)
    if not cases:
        raise SystemExit(f"no cases found in dataset: {args.dataset}")

    settings = get_settings()
    service = MemoryService(settings)
    try:
        metrics = _run_eval(service=service, cases=cases, k=max(1, args.k))
        run_id = _persist_eval_run(service=service, dataset_name=args.dataset_name, k=args.k, metrics=metrics)
        output = {"run_id": run_id, "dataset": args.dataset_name, **metrics}
        print(json.dumps(output, indent=2))
    finally:
        service.close()
    return 0


def _load_cases(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit(f"dataset must be a JSON array: {path}")
    return [item for item in payload if isinstance(item, dict)]


def _run_eval(service: MemoryService, *, cases: list[dict[str, object]], k: int) -> dict[str, object]:
    hits = 0
    mrr_total = 0.0
    citation_hits = 0
    item_details: list[dict[str, object]] = []

    for idx, case in enumerate(cases):
        project_id = str(case.get("project_id", "")).strip()
        query = str(case.get("query", "")).strip()
        if not project_id or not query:
            continue
        result = service.query_memory(
            QueryRequest(
                project_id=project_id,
                query=query,
                intent=str(case.get("intent", "auto")),
                k=k,
                token_budget=int(case.get("token_budget", 1800)),
            )
        )

        expected_chunk_ids = {str(item) for item in case.get("expected_chunk_ids", []) if str(item)}
        expected_contains = [str(item).lower() for item in case.get("expected_contains", []) if str(item)]
        expected_conversation_ids = {
            str(item) for item in case.get("expected_conversation_ids", []) if str(item)
        }

        first_match_rank: int | None = None
        first_match_has_citation = False
        for rank, candidate in enumerate(result.results, start=1):
            snippet = candidate.snippet.lower()
            source = candidate.source
            matched = False
            if expected_chunk_ids and candidate.chunk_id in expected_chunk_ids:
                matched = True
            if expected_contains and any(token in snippet for token in expected_contains):
                matched = True
            if expected_conversation_ids and source.conversation_id in expected_conversation_ids:
                matched = True
            if matched:
                first_match_rank = rank
                first_match_has_citation = bool(source.conversation_id and source.chunk_type)
                break

        hit = first_match_rank is not None
        if hit:
            hits += 1
            mrr_total += 1.0 / float(first_match_rank or 1)
            if first_match_has_citation:
                citation_hits += 1

        item_details.append(
            {
                "index": idx,
                "query": query,
                "hit": hit,
                "first_match_rank": first_match_rank,
                "citation_ok": bool(first_match_has_citation),
            }
        )

    total = max(1, len(item_details))
    recall_at_k = hits / total
    mrr = mrr_total / total
    citation_accuracy = citation_hits / total
    return {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "total_queries": len(item_details),
        "hits": hits,
        "recall_at_k": round(recall_at_k, 6),
        "mrr": round(mrr, 6),
        "citation_accuracy": round(citation_accuracy, 6),
        "items": item_details,
    }


def _persist_eval_run(
    *,
    service: MemoryService,
    dataset_name: str,
    k: int,
    metrics: dict[str, object],
) -> str:
    run_id = str(uuid4())
    with service.lock:
        service.conn.execute(
            """
            INSERT INTO retrieval_eval_runs(
              run_id, dataset_name, k, total_queries, recall_at_k, mrr, citation_accuracy, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                dataset_name,
                int(k),
                int(metrics["total_queries"]),
                float(metrics["recall_at_k"]),
                float(metrics["mrr"]),
                float(metrics["citation_accuracy"]),
                json.dumps({"items": metrics.get("items", [])}),
                str(metrics["created_at"]),
            ),
        )
        service.conn.commit()
    return run_id


if __name__ == "__main__":
    raise SystemExit(main())
