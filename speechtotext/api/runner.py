from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from speechtotext.api.events import CompleteEvent, ErrorEvent, StageEvent
from speechtotext.api.jobs import JobRegistry


def run_transcribe_job(
    registry: JobRegistry,
    job_id: str,
    audio: Path,
    language: str | None = None,
    num_speakers: int | None = None,
    backend: str | None = None,
) -> None:
    """Stub: dispatched in a thread. Task 5 fills in real Pipeline.run."""
    loop = asyncio.new_event_loop()

    def _emit_sync(event):
        asyncio.run_coroutine_threadsafe(registry.publish(job_id, event), loop).result(timeout=5.0)

    def _work():
        try:
            _emit_sync(StageEvent(stage="ingest", percent=0.0))
            _emit_sync(StageEvent(stage="ingest", percent=1.0))
            _emit_sync(CompleteEvent(transcript_id=audio.stem, paths={
                "txt": str(audio.with_suffix(".txt")),
                "json": str(audio.with_suffix(".json")),
            }))
        except Exception as exc:  # noqa: BLE001
            _emit_sync(ErrorEvent(message=f"{type(exc).__name__}: {exc}"))
        finally:
            loop.call_soon_threadsafe(loop.stop)

    t = threading.Thread(target=_work, daemon=True)
    t.start()

    def _runner():
        loop.run_forever()
        loop.close()

    threading.Thread(target=_runner, daemon=True).start()
