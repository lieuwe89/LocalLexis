from __future__ import annotations

import asyncio
import enum
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from speechtotext.api.events import (
    CompleteEvent,
    ErrorEvent,
    JobEvent,
    LineEvent,
    StageEvent,
)


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"


@dataclass
class JobRecord:
    id: str
    kind: str
    status: JobStatus = JobStatus.pending
    stage: str = ""
    percent: float = 0.0
    error: str | None = None
    transcript_id: str | None = None
    audio_path: str | None = None
    paths: dict[str, str] = field(default_factory=dict)


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._queues: dict[str, list[asyncio.Queue[JobEvent | None]]] = {}
        self._on_complete_dir: callable | None = None

    def set_on_complete_dir(self, cb) -> None:
        self._on_complete_dir = cb

    def create(self, kind: str, audio_path: str | None = None) -> str:
        job_id = uuid.uuid4().hex
        self._jobs[job_id] = JobRecord(id=job_id, kind=kind, audio_path=audio_path)
        self._queues[job_id] = []
        return job_id

    def get(self, job_id: str) -> JobRecord:
        return self._jobs[job_id]

    def all(self) -> list[JobRecord]:
        return list(self._jobs.values())

    async def publish(self, job_id: str, event: JobEvent) -> None:
        rec = self._jobs[job_id]
        if isinstance(event, StageEvent):
            rec.status = JobStatus.running
            rec.stage = event.stage
            rec.percent = event.percent
        elif isinstance(event, CompleteEvent):
            rec.status = JobStatus.complete
            rec.transcript_id = event.transcript_id
            rec.paths = dict(event.paths or {})
            if self._on_complete_dir and rec.audio_path:
                self._on_complete_dir(Path(rec.audio_path).parent)
        elif isinstance(event, ErrorEvent):
            rec.status = JobStatus.failed
            rec.error = event.message
        for q in self._queues.get(job_id, []):
            await q.put(event)
        if isinstance(event, (CompleteEvent, ErrorEvent)):
            for q in self._queues.get(job_id, []):
                await q.put(None)  # sentinel: end-of-stream

    async def subscribe(self, job_id: str) -> AsyncIterator[JobEvent]:
        q: asyncio.Queue[JobEvent | None] = asyncio.Queue()
        self._queues.setdefault(job_id, []).append(q)
        try:
            while True:
                ev = await q.get()
                if ev is None:
                    break
                yield ev
        finally:
            self._queues[job_id].remove(q)
