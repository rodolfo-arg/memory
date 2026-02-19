#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
from threading import Event

from app.config import get_settings
from app.service import MemoryService


def main() -> None:
    settings = get_settings()
    service = MemoryService(settings)

    interval = float(os.environ.get("MEMORY_EMBED_WORKER_INTERVAL", "2"))
    batch_size = int(os.environ.get("MEMORY_EMBED_BATCH_SIZE", "64"))

    stop_event = Event()

    def _stop(*_: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        while not stop_event.is_set():
            result = service.embed_pending(batch_size=batch_size)
            if result.processed_jobs:
                print(
                    f"processed={result.processed_jobs} completed={result.completed_jobs} failed={result.failed_jobs}",
                    flush=True,
                )
            stop_event.wait(interval)
    finally:
        service.close()


if __name__ == "__main__":
    main()
