from __future__ import annotations

import sqlite3

import pytest

from app.service import MemoryService


def test_bootstrap_fact_chunks_with_retry_recovers_from_locked(monkeypatch) -> None:
    service = object.__new__(MemoryService)
    attempts = {"count": 0}

    def flaky_bootstrap() -> None:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(service, "_bootstrap_fact_chunks", flaky_bootstrap)
    monkeypatch.setattr("app.service.sleep", lambda _seconds: None)

    service._bootstrap_fact_chunks_with_retry()
    assert attempts["count"] == 3


def test_bootstrap_fact_chunks_with_retry_ignores_final_locked(monkeypatch) -> None:
    service = object.__new__(MemoryService)

    def always_locked() -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(service, "_bootstrap_fact_chunks", always_locked)
    monkeypatch.setattr("app.service.sleep", lambda _seconds: None)

    service._bootstrap_fact_chunks_with_retry()


def test_bootstrap_fact_chunks_with_retry_raises_non_lock_errors(monkeypatch) -> None:
    service = object.__new__(MemoryService)

    def broken_bootstrap() -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(service, "_bootstrap_fact_chunks", broken_bootstrap)
    monkeypatch.setattr("app.service.sleep", lambda _seconds: None)

    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        service._bootstrap_fact_chunks_with_retry()
