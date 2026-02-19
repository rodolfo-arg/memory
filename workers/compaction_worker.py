#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
from threading import Event

from app.api.schemas import CompactRequest
from app.config import get_settings
from app.service import MemoryService


def main() -> None:
    settings = get_settings()
    service = MemoryService(settings)

    project_id = os.environ.get("MEMORY_PROJECT_ID", "memory")
    interval = float(os.environ.get("MEMORY_COMPACTION_INTERVAL", "3600"))
    max_chunks = int(os.environ.get("MEMORY_COMPACTION_MAX_CHUNKS", "500"))

    stop_event = Event()

    def _stop(*_: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        while not stop_event.is_set():
            result = service.compact(CompactRequest(project_id=project_id, max_chunks=max_chunks))
            if result.compacted_chunks:
                print(
                    f"compacted={result.compacted_chunks} summaries={result.summary_chunks_created}",
                    flush=True,
                )
            stop_event.wait(interval)
    finally:
        service.close()


if __name__ == "__main__":
    main()
