from __future__ import annotations

import sqlite3
from datetime import datetime, UTC


class MetricsStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def inc(self, key: str, delta: int = 1) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        self.conn.execute(
            """
            INSERT INTO metrics_counters(metric_key, metric_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(metric_key)
            DO UPDATE SET
              metric_value = metric_value + excluded.metric_value,
              updated_at = excluded.updated_at
            """,
            (key, delta, now),
        )

    def export_prometheus(self) -> str:
        rows = self.conn.execute(
            "SELECT metric_key, metric_value FROM metrics_counters ORDER BY metric_key"
        ).fetchall()
        lines = ["# TYPE memory_counter gauge"]
        for row in rows:
            key = row["metric_key"].replace("-", "_")
            lines.append(f'memory_counter{{name="{key}"}} {row["metric_value"]}')
        return "\n".join(lines) + "\n"
