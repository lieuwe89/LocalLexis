from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

from speechtotext.ingest.watch import run_watch, should_process


class WatchController:
    def __init__(self) -> None:
        self._stop: threading.Event | None = None
        self._thread: threading.Thread | None = None
        self.directory: Path | None = None
        self.events: deque[dict] = deque(maxlen=200)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, directory: Path, extensions: list[str], debounce_seconds: float,
              recursive: bool, on_file: Callable[[Path], None]) -> None:
        if self.running:
            raise RuntimeError("watcher already running")
        stop = threading.Event()
        self._stop = stop
        self.directory = directory
        self.events.clear()

        def _on_ready(path: Path) -> None:
            self.events.appendleft({"path": str(path), "ts": time.time(), "kind": "queued"})
            if should_process(path, overwrite=False):
                on_file(path)

        def _run():
            try:
                run_watch(
                    directory=directory,
                    extensions=extensions,
                    debounce_seconds=debounce_seconds,
                    recursive=recursive,
                    on_ready=_on_ready,
                    stop_event=stop,
                )
            except Exception as exc:  # noqa: BLE001
                self.events.appendleft({"kind": "error", "message": str(exc), "ts": time.time()})

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self) -> bool:
        if not self.running or self._stop is None:
            return False
        self._stop.set()
        self._thread.join(timeout=2.0)
        return True

    def status(self) -> dict:
        return {
            "running": self.running,
            "directory": str(self.directory) if self.directory else None,
            "events": list(self.events)[:50],
        }
