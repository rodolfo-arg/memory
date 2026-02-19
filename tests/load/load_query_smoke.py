#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures as futures
import statistics
import time

import httpx


def run_one(
    client: httpx.Client, base_url: str, project_id: str, query: str, use_batch: bool
) -> float:
    start = time.perf_counter()
    path = "/v1/memory/query/batch" if use_batch else "/v1/memory/query"
    if use_batch:
        payload = {
            "project_id": project_id,
            "queries": [
                {"query": query, "intent": "auto", "k": 10, "token_budget": 1200},
                {"query": "recent decision", "intent": "semantic", "k": 10, "token_budget": 1200},
            ],
        }
    else:
        payload = {
            "project_id": project_id,
            "query": query,
            "intent": "auto",
            "k": 10,
            "token_budget": 1200,
        }
    response = client.post(
        f"{base_url}{path}",
        json=payload,
        timeout=4.0,
    )
    response.raise_for_status()
    return (time.perf_counter() - start) * 1000


def main() -> None:
    parser = argparse.ArgumentParser(description="Query latency smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:4815")
    parser.add_argument("--project-id", default="memory")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--query", default="what command fixed migrations")
    parser.add_argument("--batch", action="store_true")
    args = parser.parse_args()

    durations: list[float] = []
    errors = 0

    with httpx.Client() as client:
        with futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            jobs = [
                executor.submit(
                    run_one, client, args.base_url, args.project_id, args.query, args.batch
                )
                for _ in range(args.requests)
            ]
            for job in futures.as_completed(jobs):
                try:
                    durations.append(job.result())
                except Exception:  # noqa: BLE001
                    errors += 1

    if not durations:
        raise SystemExit("all requests failed")

    durations.sort()
    p50 = statistics.median(durations)
    p95_index = max(0, int(len(durations) * 0.95) - 1)
    p95 = durations[p95_index]

    print(f"requests={args.requests} success={len(durations)} errors={errors}")
    print(f"p50_ms={p50:.2f}")
    print(f"p95_ms={p95:.2f}")


if __name__ == "__main__":
    main()
