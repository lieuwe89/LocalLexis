# LocalLexis Desktop UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship LocalLexis — a cross-platform desktop app (macOS/Windows/Linux) that wraps the existing `stt` CLI with a Tauri + React UI, exposing every CLI workflow plus a transcript library, on top of a bundled FastAPI sidecar.

**Architecture:** Three layers. (1) Tauri shell + React/Vite frontend. (2) FastAPI sidecar bundled as a PyInstaller binary, started by Tauri at launch and killed on quit. (3) Existing `speechtotext` package, consumed unchanged. Frontend ↔ sidecar over `localhost:<random>` via REST + Server-Sent Events. `.json` sidecar files on disk remain the source of truth.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, sse-starlette, httpx (tests), PyInstaller. Rust toolchain, Tauri 2.x, Vite, React 18, TypeScript, Vitest, React Testing Library. Fonts: Newsreader, Geist, Geist Mono (Google Fonts).

**Reference Spec:** `docs/superpowers/specs/2026-05-15-stt-desktop-ui-design.md`

**Design handoff:** `docs/design_handoff_locallexis/` — open `LocalLexis-standalone.html` to see the live prototype. `styles.css` + the `*.jsx` files are the canonical references for visual recreation.

---

## Conventions Used Throughout This Plan

- **Python imports** use absolute module paths (`speechtotext.api.jobs`, never relative).
- **In code**, filesystem paths use `pathlib.Path` with absolute paths.
- **In shell commands**, paths are relative to the project root (`/Users/lieuwejongsma/SpeechToText`) because git/pytest/cargo commands assume cwd = repo root.
- **Python tests** use `pytest` and live under `tests/api/`. Mirror the package layout.
- **Frontend tests** use Vitest + React Testing Library and live next to the component (`Foo.test.tsx` next to `Foo.tsx`).
- **Commits** are atomic (one task = one commit). Conventional Commits style.
- **Dependencies** are added to `pyproject.toml` / `package.json` / `Cargo.toml` only when first used.
- **Design tokens** are CSS custom properties on `:root` — never hardcode hex values in components.
- **API contract** is locked: any deviation from the spec's endpoint table must update the spec first.

---

## File Map

```
SpeechToText/
├── pyproject.toml                       # add api deps
├── speechtotext/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py                       # FastAPI app factory
│   │   ├── jobs.py                      # in-memory job registry
│   │   ├── events.py                    # SSE event types
│   │   ├── routes_jobs.py               # /jobs/*
│   │   ├── routes_transcripts.py        # /transcripts/*
│   │   ├── routes_devices.py            # /devices
│   │   ├── routes_config.py             # /config
│   │   ├── routes_watch.py              # /watch/*
│   │   └── server.py                    # `stt serve` entrypoint
│   └── cli.py                           # add `serve` subcommand
├── packaging/
│   ├── locallexis-sidecar.spec         # PyInstaller spec
│   └── README.md
├── tests/api/
│   ├── conftest.py
│   ├── test_jobs.py
│   ├── test_routes_jobs.py
│   ├── test_routes_transcripts.py
│   ├── test_routes_devices.py
│   ├── test_routes_config.py
│   └── test_routes_watch.py
├── ui/                                  # Tauri + React frontend (new top-level)
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   ├── src-tauri/                       # Rust side
│   │   ├── Cargo.toml
│   │   ├── tauri.conf.json
│   │   └── src/main.rs                  # sidecar lifecycle
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── styles/
│   │   │   ├── tokens.css               # ported from handoff styles.css
│   │   │   └── global.css
│   │   ├── api/
│   │   │   ├── client.ts                # fetch wrapper + base URL discovery
│   │   │   ├── types.ts                 # API DTOs
│   │   │   └── sse.ts                   # SSE subscription helper
│   │   ├── stores/
│   │   │   ├── jobs.ts
│   │   │   ├── transcripts.ts
│   │   │   ├── library.ts
│   │   │   ├── recording.ts
│   │   │   └── config.ts
│   │   ├── primitives/
│   │   │   ├── Icon.tsx
│   │   │   └── colors.ts                # SPEAKER_COLORS palette
│   │   ├── chrome/
│   │   │   ├── Window.tsx               # titlebar + frame
│   │   │   ├── Sidebar.tsx
│   │   │   └── MainHeader.tsx
│   │   └── screens/
│   │       ├── IdleScreen.tsx
│   │       ├── ProgressScreen.tsx
│   │       ├── CompleteScreen.tsx
│   │       ├── RecordScreen.tsx
│   │       ├── LibraryScreen.tsx
│   │       ├── WatchScreen.tsx
│   │       └── SettingsScreen.tsx
└── docs/design_handoff_locallexis/
    └── progress-screen.md               # design notes added during plan
    └── library-screen.md
    └── watch-screen.md
    └── settings-screen.md
```

---

## Milestones

1. **Backend (Tasks 1–11)** — FastAPI sidecar + `stt serve` command. Backend ships independently; CLI remains intact.
2. **Packaging (Tasks 12–13)** — PyInstaller binary, cross-platform CI.
3. **Frontend scaffold (Tasks 14–18)** — Tauri + Vite + React. Window chrome, design tokens, sidecar lifecycle.
4. **Chrome (Tasks 19–21)** — Sidebar, main header, Icon primitive.
5. **Idle screen (Task 22)** — high-fi recreation.
6. **In-progress (Tasks 23–24)** — design note + screen.
7. **Complete screen (Task 25)** — high-fi recreation.
8. **Record screen (Task 26)** — high-fi recreation.
9. **Library, Watch, Settings (Tasks 27–32)** — design note + screen for each.
10. **Ship (Tasks 33–35)** — Tauri smoke test, cross-platform CI for the bundled app, README.

---

# Milestone 1 — Backend

### Task 1: Add FastAPI dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add api extra to `[project.optional-dependencies]`**

Edit `pyproject.toml` to add:

```toml
api = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "sse-starlette>=2.0",
    "httpx>=0.27",  # test client; runtime cost is fine, keep in api group
]
```

- [ ] **Step 2: Install**

Run: `pip install -e ".[dev,api]"`
Expected: clean install, no version conflicts.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add api extra (fastapi, uvicorn, sse-starlette, httpx)"
```

---

### Task 2: Job registry — model

In-memory registry that tracks job state and exposes an async event stream per job. No persistence: server restart wipes jobs.

**Files:**
- Create: `speechtotext/api/__init__.py`
- Create: `speechtotext/api/events.py`
- Create: `speechtotext/api/jobs.py`
- Create: `tests/api/__init__.py`
- Create: `tests/api/conftest.py`
- Create: `tests/api/test_jobs.py`

- [ ] **Step 1: Write the failing test**

`tests/api/test_jobs.py`:

```python
import asyncio
import pytest

from speechtotext.api.events import StageEvent, LineEvent, CompleteEvent, ErrorEvent
from speechtotext.api.jobs import JobRegistry, JobStatus


@pytest.mark.asyncio
async def test_create_job_returns_unique_id():
    reg = JobRegistry()
    a = reg.create(kind="transcribe", audio_path="/tmp/a.mp3")
    b = reg.create(kind="transcribe", audio_path="/tmp/b.mp3")
    assert a != b
    assert reg.get(a).status == JobStatus.pending


@pytest.mark.asyncio
async def test_publish_and_subscribe():
    reg = JobRegistry()
    job_id = reg.create(kind="transcribe", audio_path="/tmp/x.mp3")
    received: list = []

    async def consumer():
        async for ev in reg.subscribe(job_id):
            received.append(ev)
            if isinstance(ev, CompleteEvent):
                break

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0)  # let consumer attach
    await reg.publish(job_id, StageEvent(stage="asr", percent=50))
    await reg.publish(job_id, LineEvent(speaker="SPEAKER_00", ts=1.0, text="hi"))
    await reg.publish(job_id, CompleteEvent(transcript_id="x", paths={"txt": "/tmp/x.txt", "json": "/tmp/x.json"}))
    await asyncio.wait_for(task, timeout=1.0)

    assert [type(e).__name__ for e in received] == ["StageEvent", "LineEvent", "CompleteEvent"]
    assert reg.get(job_id).status == JobStatus.complete


@pytest.mark.asyncio
async def test_error_event_marks_job_failed():
    reg = JobRegistry()
    job_id = reg.create(kind="transcribe", audio_path="/tmp/x.mp3")
    await reg.publish(job_id, ErrorEvent(message="boom"))
    assert reg.get(job_id).status == JobStatus.failed
    assert reg.get(job_id).error == "boom"
```

`tests/api/conftest.py`:

```python
import pytest_asyncio  # noqa: F401  # ensure plugin loads


def pytest_collection_modifyitems(config, items):
    pass
```

- [ ] **Step 2: Add async test deps**

Edit `pyproject.toml` `dev` extra:

```toml
"pytest-asyncio>=0.23",
"anyio>=4.0",
```

Run: `pip install -e ".[dev,api]"`

Add to `[tool.pytest.ini_options]`:

```toml
asyncio_mode = "auto"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/api/test_jobs.py -v`
Expected: ImportError on `speechtotext.api.events`.

- [ ] **Step 4: Implement events**

`speechtotext/api/__init__.py`:

```python
```

`speechtotext/api/events.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class StageEvent:
    type: Literal["stage"] = "stage"
    stage: str = ""
    percent: float = 0.0


@dataclass(frozen=True)
class LineEvent:
    type: Literal["line"] = "line"
    speaker: str = ""
    ts: float = 0.0
    text: str = ""


@dataclass(frozen=True)
class CompleteEvent:
    type: Literal["complete"] = "complete"
    transcript_id: str = ""
    paths: dict[str, str] = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ErrorEvent:
    type: Literal["error"] = "error"
    message: str = ""


JobEvent = StageEvent | LineEvent | CompleteEvent | ErrorEvent
```

- [ ] **Step 5: Implement JobRegistry**

`speechtotext/api/jobs.py`:

```python
from __future__ import annotations

import asyncio
import enum
import uuid
from dataclasses import dataclass, field
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
```

- [ ] **Step 6: Run tests and verify pass**

Run: `pytest tests/api/test_jobs.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml speechtotext/api tests/api
git commit -m "feat(api): job registry with async event subscription"
```

---

### Task 3: FastAPI app factory + healthcheck

**Files:**
- Create: `speechtotext/api/app.py`
- Create: `tests/api/test_app.py`

- [ ] **Step 1: Write the failing test**

`tests/api/test_app.py`:

```python
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


def test_health_endpoint():
    app = create_app()
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_app_exposes_job_registry_via_state():
    app = create_app()
    assert hasattr(app.state, "jobs")
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/api/test_app.py -v`
Expected: ImportError on `speechtotext.api.app`.

- [ ] **Step 3: Implement app factory**

`speechtotext/api/app.py`:

```python
from __future__ import annotations

from fastapi import FastAPI

from speechtotext.api.jobs import JobRegistry


def create_app() -> FastAPI:
    app = FastAPI(title="LocalLexis", version="0.1.0")
    app.state.jobs = JobRegistry()

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    return app
```

- [ ] **Step 4: Run + commit**

```bash
pytest tests/api/test_app.py -v
git add speechtotext/api/app.py tests/api/test_app.py
git commit -m "feat(api): FastAPI app factory with health endpoint"
```

---

### Task 4: `POST /jobs/transcribe` + state lookup

Wires the existing `Pipeline.run()` to a job, runs it in a background thread, publishes events.

**Files:**
- Create: `speechtotext/api/runner.py`
- Create: `speechtotext/api/routes_jobs.py`
- Modify: `speechtotext/api/app.py`
- Create: `tests/api/test_routes_jobs.py`

- [ ] **Step 1: Write the failing test**

`tests/api/test_routes_jobs.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app
from speechtotext.api.jobs import JobStatus


@pytest.fixture
def app_with_fake_runner(monkeypatch):
    app = create_app()
    fake_run = MagicMock()
    monkeypatch.setattr("speechtotext.api.runner.run_transcribe_job", fake_run)
    return app, fake_run


def test_post_transcribe_creates_job_and_dispatches(tmp_path: Path, app_with_fake_runner):
    app, fake_run = app_with_fake_runner
    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"fake")
    client = TestClient(app)

    r = client.post("/jobs/transcribe", json={"path": str(audio)})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    assert isinstance(job_id, str) and len(job_id) > 0
    fake_run.assert_called_once()
    args, _ = fake_run.call_args
    assert args[0] is app.state.jobs
    assert args[1] == job_id
    assert args[2] == audio


def test_post_transcribe_rejects_missing_file(tmp_path: Path, app_with_fake_runner):
    app, _ = app_with_fake_runner
    client = TestClient(app)
    r = client.post("/jobs/transcribe", json={"path": str(tmp_path / "nope.mp3")})
    assert r.status_code == 404


def test_get_job_returns_state(tmp_path: Path, app_with_fake_runner):
    app, _ = app_with_fake_runner
    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"fake")
    client = TestClient(app)
    job_id = client.post("/jobs/transcribe", json={"path": str(audio)}).json()["job_id"]

    r = client.get(f"/jobs/{job_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == job_id
    assert body["status"] == JobStatus.pending.value
```

- [ ] **Step 2: Run + verify failure**

Run: `pytest tests/api/test_routes_jobs.py -v`
Expected: ImportError on `speechtotext.api.routes_jobs`.

- [ ] **Step 3: Implement runner (skeleton — real `Pipeline.run` wiring in Task 5)**

`speechtotext/api/runner.py`:

```python
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
        asyncio.run_coroutine_threadsafe(registry.publish(job_id, event), loop).result()

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
```

- [ ] **Step 4: Implement routes**

`speechtotext/api/routes_jobs.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from speechtotext.api import runner

router = APIRouter()


class TranscribeRequest(BaseModel):
    path: str
    language: str | None = None
    num_speakers: int | None = None
    backend: str | None = None


@router.post("/jobs/transcribe", status_code=202)
def post_transcribe(req: TranscribeRequest, request: Request) -> dict:
    audio = Path(req.path)
    if not audio.exists() or audio.is_dir():
        raise HTTPException(status_code=404, detail=f"audio not found: {audio}")
    registry = request.app.state.jobs
    job_id = registry.create(kind="transcribe", audio_path=str(audio))
    runner.run_transcribe_job(
        registry, job_id, audio,
        language=req.language,
        num_speakers=req.num_speakers,
        backend=req.backend,
    )
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    try:
        rec = request.app.state.jobs.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    return {
        "id": rec.id,
        "kind": rec.kind,
        "status": rec.status.value,
        "stage": rec.stage,
        "percent": rec.percent,
        "error": rec.error,
        "transcript_id": rec.transcript_id,
        "audio_path": rec.audio_path,
        "paths": rec.paths,
    }
```

- [ ] **Step 5: Register router in app**

Edit `speechtotext/api/app.py` — add after `app.state.jobs = JobRegistry()`:

```python
from speechtotext.api.routes_jobs import router as jobs_router  # noqa: E402

app.include_router(jobs_router)
```

(Move import to top of file properly; the comment is just for clarity.)

- [ ] **Step 6: Run + verify pass**

Run: `pytest tests/api/test_routes_jobs.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add speechtotext/api tests/api/test_routes_jobs.py
git commit -m "feat(api): POST /jobs/transcribe + GET /jobs/{id} (stub runner)"
```

---

### Task 5: Wire `Pipeline.run` into the runner

Replace the stub in `runner.py` with real `Pipeline.run()` calls. Bridge the existing `ProgressEvent` → `StageEvent`. Map ASR segments → `LineEvent`s after diarization+merge by emitting them sequentially after `merge` stage completes (simplest faithful mapping — no per-token streaming).

**Files:**
- Modify: `speechtotext/api/runner.py`
- Create: `tests/api/test_runner.py`

- [ ] **Step 1: Write the failing test**

`tests/api/test_runner.py`:

```python
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from speechtotext.api.events import CompleteEvent, LineEvent, StageEvent
from speechtotext.api.jobs import JobRegistry, JobStatus
from speechtotext.api.runner import run_transcribe_job
from speechtotext.models import LabeledSegment, Transcript


def _fake_transcript(audio: Path) -> Transcript:
    return Transcript(
        audio_path=audio,
        duration_seconds=2.0,
        language="en",
        speakers={"SPEAKER_00": "Speaker 1"},
        segments=[LabeledSegment(0.0, 1.0, "hello", "SPEAKER_00")],
        models={"asr": "fake", "diarizer": "fake", "backend": "cpu"},
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_runner_emits_stage_line_complete(tmp_path):
    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"fake")
    reg = JobRegistry()
    job_id = reg.create(kind="transcribe", audio_path=str(audio))

    with patch("speechtotext.api.runner._build_pipeline") as build, \
         patch("speechtotext.api.runner.write_transcript") as wt:
        pipe = MagicMock()
        pipe.run.return_value = _fake_transcript(audio)
        build.return_value = (pipe, "cpu")
        wt.return_value = (audio.with_suffix(".txt"), audio.with_suffix(".json"))

        run_transcribe_job(reg, job_id, audio)

        events = []
        async for ev in reg.subscribe(job_id):
            events.append(ev)

    types = [type(e).__name__ for e in events]
    assert "StageEvent" in types
    assert "LineEvent" in types
    assert types[-1] == "CompleteEvent"
    assert reg.get(job_id).status == JobStatus.complete
```

- [ ] **Step 2: Run + verify failure**

Run: `pytest tests/api/test_runner.py -v`
Expected: AttributeError on `_build_pipeline` (doesn't exist yet).

- [ ] **Step 3: Implement runner**

Replace `speechtotext/api/runner.py`:

```python
from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from speechtotext.api.events import (
    CompleteEvent,
    ErrorEvent,
    LineEvent,
    StageEvent,
)
from speechtotext.api.jobs import JobRegistry
from speechtotext.asr.faster_whisper import FasterWhisperASR
from speechtotext.backend import resolve_backend
from speechtotext.config import Config, DEFAULT_CONFIG_PATH, load_config
from speechtotext.diarize.pyannote import PyannoteDiarizer
from speechtotext.models import ProgressEvent, Transcript
from speechtotext.pipeline import Pipeline
from speechtotext.writer import write_transcript


def _build_pipeline(cfg: Config, cli_backend: str | None) -> tuple[Pipeline, str]:
    backend = resolve_backend(cli_flag=cli_backend, config=cfg)
    asr = FasterWhisperASR(
        model_size=cfg.asr_model, backend=backend, download_root=cfg.model_cache_dir
    )
    if not cfg.hf_token:
        raise RuntimeError("hf_token not set; configure via /config or config.toml")
    diarizer = PyannoteDiarizer(hf_token=cfg.hf_token, backend=backend)
    return Pipeline(config=cfg, asr=asr, diarizer=diarizer, resolved_backend=backend), backend


def _make_emit(loop: asyncio.AbstractEventLoop, registry: JobRegistry, job_id: str):
    def emit(event):
        asyncio.run_coroutine_threadsafe(registry.publish(job_id, event), loop).result()
    return emit


def _bridge_progress(emit) -> "callable":
    def on_progress(pe: ProgressEvent) -> None:
        emit(StageEvent(stage=pe.stage, percent=pe.pct))
    return on_progress


def run_transcribe_job(
    registry: JobRegistry,
    job_id: str,
    audio: Path,
    language: str | None = None,
    num_speakers: int | None = None,
    backend: str | None = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> None:
    loop = asyncio.new_event_loop()
    emit = _make_emit(loop, registry, job_id)

    def _work() -> None:
        try:
            cfg = load_config(config_path=config_path)
            pipeline, _resolved = _build_pipeline(cfg, backend)
            transcript: Transcript = pipeline.run(
                audio,
                language=None if language in (None, "auto") else language,
                num_speakers=num_speakers,
                on_progress=_bridge_progress(emit),
            )
            emit(StageEvent(stage="write", percent=0.0))
            txt, json_path = write_transcript(transcript)
            for seg in transcript.segments:
                emit(LineEvent(speaker=seg.speaker_id, ts=seg.start, text=seg.text))
            emit(CompleteEvent(
                transcript_id=audio.stem,
                paths={"txt": str(txt), "json": str(json_path)},
            ))
        except Exception as exc:  # noqa: BLE001
            emit(ErrorEvent(message=f"{type(exc).__name__}: {exc}"))
        finally:
            loop.call_soon_threadsafe(loop.stop)

    threading.Thread(target=_work, daemon=True).start()
    threading.Thread(target=lambda: (loop.run_forever(), loop.close()), daemon=True).start()
```

- [ ] **Step 4: Run + verify pass**

Run: `pytest tests/api/test_runner.py tests/api/test_routes_jobs.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/runner.py tests/api/test_runner.py
git commit -m "feat(api): wire Pipeline.run into transcribe job runner"
```

---

### Task 6: SSE stream — `GET /jobs/{id}/stream`

**Files:**
- Modify: `speechtotext/api/routes_jobs.py`
- Modify: `tests/api/test_routes_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/api/test_routes_jobs.py`:

```python
import json
import threading
import time

from speechtotext.api.events import CompleteEvent, StageEvent


def test_stream_yields_events_until_complete(tmp_path, app_with_fake_runner):
    app, _ = app_with_fake_runner
    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"fake")
    client = TestClient(app)

    job_id = client.post("/jobs/transcribe", json={"path": str(audio)}).json()["job_id"]
    reg = app.state.jobs

    def producer():
        time.sleep(0.05)
        import asyncio
        asyncio.run(reg.publish(job_id, StageEvent(stage="asr", percent=0.5)))
        asyncio.run(reg.publish(job_id, CompleteEvent(
            transcript_id="x", paths={"txt": "/x.txt", "json": "/x.json"}
        )))

    threading.Thread(target=producer, daemon=True).start()

    with client.stream("GET", f"/jobs/{job_id}/stream") as r:
        assert r.status_code == 200
        events = []
        for line in r.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            events.append(json.loads(line[len("data: "):]))
            if events[-1]["type"] == "complete":
                break

    assert events[0]["type"] == "stage"
    assert events[-1]["type"] == "complete"
```

- [ ] **Step 2: Run + verify failure**

Run: `pytest tests/api/test_routes_jobs.py::test_stream_yields_events_until_complete -v`
Expected: 404.

- [ ] **Step 3: Add the route**

Append to `speechtotext/api/routes_jobs.py`:

```python
from dataclasses import asdict
from sse_starlette.sse import EventSourceResponse


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str, request: Request):
    registry = request.app.state.jobs
    try:
        registry.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")

    async def event_gen():
        async for ev in registry.subscribe(job_id):
            yield {"event": "message", "data": _json_dumps(asdict(ev))}

    return EventSourceResponse(event_gen())


def _json_dumps(obj: dict) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)
```

- [ ] **Step 4: Run + verify pass + commit**

```bash
pytest tests/api/test_routes_jobs.py -v
git add speechtotext/api/routes_jobs.py tests/api/test_routes_jobs.py
git commit -m "feat(api): SSE stream for /jobs/{id}/stream"
```

---

### Task 7: Record endpoints — `POST /jobs/record` + `POST /jobs/{id}/stop`

A recording job runs `record_to_wav` in a thread with a `stop_event`. On stop, the registry holds the WAV path so the frontend can chain a transcribe job.

**Files:**
- Modify: `speechtotext/api/runner.py`
- Modify: `speechtotext/api/routes_jobs.py`
- Modify: `tests/api/test_routes_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/api/test_routes_jobs.py`:

```python
from unittest.mock import patch


def test_post_record_creates_job(tmp_path, monkeypatch):
    from speechtotext.api.app import create_app
    app = create_app()
    out = tmp_path / "rec.wav"
    client = TestClient(app)

    with patch("speechtotext.api.runner.record_to_wav") as rec:
        # block until stop
        def fake_record(out_path, **kw):
            kw["stop_event"].wait()
            out_path.write_bytes(b"WAVE")
            return out_path
        rec.side_effect = fake_record

        r = client.post("/jobs/record", json={"out": str(out)})
        assert r.status_code == 202
        job_id = r.json()["job_id"]

        r2 = client.post(f"/jobs/{job_id}/stop")
        assert r2.status_code == 200
        assert out.exists()
```

- [ ] **Step 2: Run + verify failure**

Run: `pytest tests/api/test_routes_jobs.py::test_post_record_creates_job -v`
Expected: 404 or import error.

- [ ] **Step 3: Implement record runner**

Append to `speechtotext/api/runner.py`:

```python
import threading as _threading

from speechtotext.ingest.mic import record_to_wav  # re-exported for tests

_STOP_EVENTS: dict[str, _threading.Event] = {}


def run_record_job(
    registry: JobRegistry,
    job_id: str,
    out_path: Path,
    device: str | None = None,
) -> None:
    loop = asyncio.new_event_loop()
    emit = _make_emit(loop, registry, job_id)
    stop = _threading.Event()
    _STOP_EVENTS[job_id] = stop

    def _work():
        try:
            emit(StageEvent(stage="record", percent=0.0))
            record_to_wav(out_path, device=device, stop_event=stop)
            emit(StageEvent(stage="record", percent=1.0))
            emit(CompleteEvent(
                transcript_id="",
                paths={"wav": str(out_path)},
            ))
        except Exception as exc:  # noqa: BLE001
            emit(ErrorEvent(message=f"{type(exc).__name__}: {exc}"))
        finally:
            _STOP_EVENTS.pop(job_id, None)
            loop.call_soon_threadsafe(loop.stop)

    threading.Thread(target=_work, daemon=True).start()
    threading.Thread(target=lambda: (loop.run_forever(), loop.close()), daemon=True).start()


def stop_record_job(job_id: str) -> bool:
    ev = _STOP_EVENTS.get(job_id)
    if ev is None:
        return False
    ev.set()
    return True
```

- [ ] **Step 4: Add routes**

Append to `speechtotext/api/routes_jobs.py`:

```python
class RecordRequest(BaseModel):
    out: str
    device: str | None = None


@router.post("/jobs/record", status_code=202)
def post_record(req: RecordRequest, request: Request) -> dict:
    out = Path(req.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    registry = request.app.state.jobs
    job_id = registry.create(kind="record", audio_path=str(out))
    runner.run_record_job(registry, job_id, out, device=req.device)
    return {"job_id": job_id}


@router.post("/jobs/{job_id}/stop")
def stop_job(job_id: str) -> dict:
    ok = runner.stop_record_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not recording or already stopped")
    return {"ok": True}
```

- [ ] **Step 5: Run + verify pass + commit**

```bash
pytest tests/api/test_routes_jobs.py -v
git add speechtotext/api tests/api/test_routes_jobs.py
git commit -m "feat(api): record endpoints (POST /jobs/record, POST /jobs/{id}/stop)"
```

---

### Task 8: Transcripts library — list / get / relabel

`/transcripts` scans output directories for `.json` sidecars. Output dirs come from config plus an in-memory "known dirs" set (every directory we've ever transcribed into).

**Files:**
- Create: `speechtotext/api/library.py`
- Create: `speechtotext/api/routes_transcripts.py`
- Modify: `speechtotext/api/app.py`
- Create: `tests/api/test_routes_transcripts.py`

- [ ] **Step 1: Write the failing test**

`tests/api/test_routes_transcripts.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


@pytest.fixture
def app_with_lib(tmp_path):
    app = create_app()
    app.state.library_dirs.add(tmp_path)
    sample = {
        "version": 1,
        "audio_path": str(tmp_path / "meet.mp3"),
        "duration_seconds": 60.0,
        "language": "en",
        "speakers": {"SPEAKER_00": "Alice"},
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": "hi"}],
        "models": {"asr": "faster-whisper:tiny"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (tmp_path / "meet.json").write_text(json.dumps(sample))
    return app


def test_list_transcripts_returns_metadata(app_with_lib):
    client = TestClient(app_with_lib)
    r = client.get("/transcripts")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    item = items[0]
    assert item["id"] == "meet"
    assert item["duration_seconds"] == 60.0
    assert item["speakers"] == 1


def test_get_transcript_returns_full_json(app_with_lib):
    client = TestClient(app_with_lib)
    r = client.get("/transcripts/meet")
    assert r.status_code == 200
    assert r.json()["segments"][0]["text"] == "hi"


def test_patch_relabel_rewrites_sidecar(app_with_lib, tmp_path):
    client = TestClient(app_with_lib)
    r = client.patch("/transcripts/meet/relabel", json={"SPEAKER_00": "Bob"})
    assert r.status_code == 200
    raw = json.loads((tmp_path / "meet.json").read_text())
    assert raw["speakers"]["SPEAKER_00"] == "Bob"
```

- [ ] **Step 2: Implement library helper**

`speechtotext/api/library.py`:

```python
from __future__ import annotations

import json
from pathlib import Path


def scan_dirs(dirs: set[Path]) -> list[dict]:
    out: list[dict] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for json_path in d.glob("*.json"):
            try:
                raw = json.loads(json_path.read_text(encoding="utf-8"))
                out.append({
                    "id": json_path.stem,
                    "path": str(json_path),
                    "audio_path": raw.get("audio_path"),
                    "duration_seconds": raw.get("duration_seconds"),
                    "language": raw.get("language"),
                    "speakers": len(raw.get("speakers", {})),
                    "created_at": raw.get("created_at"),
                    "models": raw.get("models", {}),
                })
            except (json.JSONDecodeError, OSError):
                out.append({"id": json_path.stem, "path": str(json_path), "error": "parse"})
    out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return out


def find_sidecar(dirs: set[Path], transcript_id: str) -> Path | None:
    for d in dirs:
        candidate = d / f"{transcript_id}.json"
        if candidate.exists():
            return candidate
    return None
```

- [ ] **Step 3: Implement routes**

`speechtotext/api/routes_transcripts.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from speechtotext.api.library import find_sidecar, scan_dirs
from speechtotext.relabel import relabel

router = APIRouter()


@router.get("/transcripts")
def list_transcripts(request: Request) -> list[dict]:
    return scan_dirs(request.app.state.library_dirs)


@router.get("/transcripts/{tid}")
def get_transcript(tid: str, request: Request) -> dict:
    p = find_sidecar(request.app.state.library_dirs, tid)
    if p is None:
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")
    return json.loads(p.read_text(encoding="utf-8"))


@router.patch("/transcripts/{tid}/relabel")
def patch_relabel(tid: str, mapping: dict[str, str], request: Request) -> dict:
    p = find_sidecar(request.app.state.library_dirs, tid)
    if p is None:
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")
    try:
        relabel(p, mapping)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}
```

- [ ] **Step 4: Wire `library_dirs` into app + register router**

Edit `speechtotext/api/app.py`:

```python
from pathlib import Path

# inside create_app(), after app.state.jobs = JobRegistry():
app.state.library_dirs: set[Path] = set()

# default: config default_out_dir if set
from speechtotext.config import load_config
try:
    _cfg = load_config()
    if _cfg.default_out_dir:
        app.state.library_dirs.add(_cfg.default_out_dir)
except Exception:
    pass

from speechtotext.api.routes_transcripts import router as transcripts_router
app.include_router(transcripts_router)
```

Also: when a transcribe job completes successfully, add the output dir to `library_dirs`. Edit `speechtotext/api/runner.py` `run_transcribe_job._work()` after `write_transcript(...)`:

```python
registry._library_dirs_add(audio.parent)  # see step 5
```

- [ ] **Step 5: Plumb a callback for library updates**

Edit `JobRegistry` to accept an optional `on_complete_dir` callback (cleaner than reaching into `app.state` from the runner). Add to `JobRegistry.__init__`:

```python
self._on_complete_dir: callable | None = None

def set_on_complete_dir(self, cb) -> None:
    self._on_complete_dir = cb
```

In `publish()`, after handling `CompleteEvent`:

```python
if isinstance(event, CompleteEvent) and self._on_complete_dir and rec.audio_path:
    self._on_complete_dir(Path(rec.audio_path).parent)
```

In `create_app()` after `app.state.library_dirs`:

```python
app.state.jobs.set_on_complete_dir(app.state.library_dirs.add)
```

- [ ] **Step 6: Run + verify pass + commit**

```bash
pytest tests/api/test_routes_transcripts.py -v
git add speechtotext/api tests/api/test_routes_transcripts.py
git commit -m "feat(api): transcripts library (list/get/relabel)"
```

---

### Task 9: `GET /devices` + `GET /config` + `PATCH /config`

**Files:**
- Create: `speechtotext/api/routes_devices.py`
- Create: `speechtotext/api/routes_config.py`
- Modify: `speechtotext/api/app.py`
- Create: `tests/api/test_routes_devices.py`
- Create: `tests/api/test_routes_config.py`

- [ ] **Step 1: Devices test**

`tests/api/test_routes_devices.py`:

```python
from dataclasses import asdict
from unittest.mock import patch

from fastapi.testclient import TestClient

from speechtotext.api.app import create_app
from speechtotext.devices import AudioDevice


def test_devices_endpoint_returns_inputs():
    fake = [AudioDevice(index=0, name="MacBook Mic", channels=1,
                        sample_rate=48000.0, default=True, hint="mic")]
    with patch("speechtotext.api.routes_devices.list_inputs", return_value=fake):
        app = create_app()
        r = TestClient(app).get("/devices")
        assert r.status_code == 200
        assert r.json() == [asdict(fake[0])]
```

- [ ] **Step 2: Devices route**

`speechtotext/api/routes_devices.py`:

```python
from dataclasses import asdict
from fastapi import APIRouter

from speechtotext.devices import list_inputs

router = APIRouter()


@router.get("/devices")
def get_devices(include_all: bool = False) -> list[dict]:
    return [asdict(d) for d in list_inputs(include_all=include_all)]
```

- [ ] **Step 3: Config test**

`tests/api/test_routes_config.py`:

```python
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


def test_config_get_returns_defaults_and_hf_flag(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("speechtotext.api.routes_config.DEFAULT_CONFIG_PATH", cfg_path)
    app = create_app()
    r = TestClient(app).get("/config")
    assert r.status_code == 200
    body = r.json()
    assert body["backend"] == "auto"
    assert body["hf_token_set"] is False


def test_config_patch_writes_toml(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("speechtotext.api.routes_config.DEFAULT_CONFIG_PATH", cfg_path)
    app = create_app()
    r = TestClient(app).patch("/config", json={"asr_model": "small", "hf_token": "hf_xxx"})
    assert r.status_code == 200
    raw = tomllib.loads(cfg_path.read_text())
    assert raw["asr_model"] == "small"
    assert raw["hf_token"] == "hf_xxx"
```

- [ ] **Step 4: Config route**

`speechtotext/api/routes_config.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from speechtotext.config import DEFAULT_CONFIG_PATH, load_config

router = APIRouter()


def _public(cfg) -> dict:
    return {
        "backend": cfg.backend,
        "asr_model": cfg.asr_model,
        "hf_token_set": bool(cfg.hf_token),
        "model_cache_dir": str(cfg.model_cache_dir),
        "default_out_dir": str(cfg.default_out_dir) if cfg.default_out_dir else None,
        "watch": {
            "recursive": cfg.watch.recursive,
            "debounce_seconds": cfg.watch.debounce_seconds,
            "extensions": list(cfg.watch.extensions),
        },
    }


@router.get("/config")
def get_config() -> dict:
    cfg = load_config(config_path=DEFAULT_CONFIG_PATH)
    return _public(cfg)


@router.patch("/config")
def patch_config(updates: dict[str, Any]) -> dict:
    path: Path = DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        import tomllib
        existing = tomllib.loads(path.read_text())
    existing.update({k: v for k, v in updates.items() if not isinstance(v, dict)})
    if isinstance(updates.get("watch"), dict):
        existing.setdefault("watch", {}).update(updates["watch"])

    def _dump_toml(d: dict) -> str:
        # minimal hand-rolled TOML — only flat keys + [watch]
        lines: list[str] = []
        for k, v in d.items():
            if k == "watch":
                continue
            lines.append(_kv(k, v))
        if "watch" in d:
            lines.append("\n[watch]")
            for k, v in d["watch"].items():
                lines.append(_kv(k, v))
        return "\n".join(lines) + "\n"

    def _kv(k: str, v) -> str:
        if isinstance(v, bool):
            return f"{k} = {'true' if v else 'false'}"
        if isinstance(v, int):
            return f"{k} = {v}"
        if isinstance(v, list):
            inside = ", ".join(f'"{x}"' for x in v)
            return f"{k} = [{inside}]"
        return f'{k} = "{v}"'

    path.write_text(_dump_toml(existing))
    return _public(load_config(config_path=path))
```

- [ ] **Step 5: Register both routers**

Edit `speechtotext/api/app.py`:

```python
from speechtotext.api.routes_devices import router as devices_router
from speechtotext.api.routes_config import router as config_router
app.include_router(devices_router)
app.include_router(config_router)
```

- [ ] **Step 6: Run + commit**

```bash
pytest tests/api/test_routes_devices.py tests/api/test_routes_config.py -v
git add speechtotext/api tests/api/test_routes_devices.py tests/api/test_routes_config.py
git commit -m "feat(api): /devices, GET+PATCH /config endpoints"
```

---

### Task 10: Watch folder endpoints

`POST /watch/start` spawns `run_watch` in a daemon thread, storing the stop event. Each detected file kicks off a transcribe job via the same runner. `/watch/status` returns the daemon state + last N events. `POST /watch/stop` sets the stop event.

**Files:**
- Create: `speechtotext/api/watcher.py`
- Create: `speechtotext/api/routes_watch.py`
- Modify: `speechtotext/api/app.py`
- Create: `tests/api/test_routes_watch.py`

- [ ] **Step 1: Test**

`tests/api/test_routes_watch.py`:

```python
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


def test_watch_start_and_stop(tmp_path: Path):
    app = create_app()
    client = TestClient(app)
    with patch("speechtotext.api.watcher.run_watch") as rw:
        rw.side_effect = lambda **kw: kw["stop_event"].wait()  # blocks until stop
        r = client.post("/watch/start", json={"directory": str(tmp_path)})
        assert r.status_code == 200
        assert client.get("/watch/status").json()["running"] is True
        r2 = client.post("/watch/stop")
        assert r2.status_code == 200
        time.sleep(0.05)
        assert client.get("/watch/status").json()["running"] is False
```

- [ ] **Step 2: Implement watcher controller**

`speechtotext/api/watcher.py`:

```python
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
```

- [ ] **Step 3: Routes**

`speechtotext/api/routes_watch.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from speechtotext.api import runner
from speechtotext.config import load_config

router = APIRouter()


class WatchStartRequest(BaseModel):
    directory: str
    recursive: bool = False


@router.post("/watch/start")
def start(req: WatchStartRequest, request: Request) -> dict:
    d = Path(req.directory)
    if not d.is_dir():
        raise HTTPException(status_code=400, detail=f"not a directory: {d}")
    cfg = load_config()
    registry = request.app.state.jobs
    ctrl = request.app.state.watcher

    def _on_file(path: Path):
        job_id = registry.create(kind="transcribe", audio_path=str(path))
        runner.run_transcribe_job(registry, job_id, path)

    try:
        ctrl.start(
            directory=d,
            extensions=list(cfg.watch.extensions),
            debounce_seconds=cfg.watch.debounce_seconds,
            recursive=req.recursive,
            on_file=_on_file,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return ctrl.status()


@router.post("/watch/stop")
def stop(request: Request) -> dict:
    request.app.state.watcher.stop()
    return request.app.state.watcher.status()


@router.get("/watch/status")
def status(request: Request) -> dict:
    return request.app.state.watcher.status()
```

- [ ] **Step 4: Wire into app**

In `create_app()`:

```python
from speechtotext.api.watcher import WatchController
app.state.watcher = WatchController()

from speechtotext.api.routes_watch import router as watch_router
app.include_router(watch_router)
```

- [ ] **Step 5: Run + commit**

```bash
pytest tests/api/test_routes_watch.py -v
git add speechtotext/api tests/api/test_routes_watch.py
git commit -m "feat(api): watch folder endpoints (/watch/start, stop, status)"
```

---

### Task 11: `stt serve` CLI subcommand

Adds a CLI subcommand so the existing `stt` binary can launch the API for local dev and (in packaged builds) as the PyInstaller entrypoint.

**Files:**
- Create: `speechtotext/api/server.py`
- Modify: `speechtotext/cli.py`
- Create: `tests/api/test_server.py`

- [ ] **Step 1: Test**

`tests/api/test_server.py`:

```python
import socket

from speechtotext.api.server import pick_port


def test_pick_port_returns_available_port():
    p = pick_port()
    assert 1024 < p < 65536
    s = socket.socket()
    s.bind(("127.0.0.1", p))
    s.close()
```

- [ ] **Step 2: Implement server bootstrap**

`speechtotext/api/server.py`:

```python
from __future__ import annotations

import json
import socket
import sys

import uvicorn

from speechtotext.api.app import create_app


def pick_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def run(host: str = "127.0.0.1", port: int | None = None, print_handshake: bool = True) -> None:
    p = port or pick_port()
    if print_handshake:
        sys.stdout.write(json.dumps({"locallexis": {"host": host, "port": p}}) + "\n")
        sys.stdout.flush()
    uvicorn.run(create_app(), host=host, port=p, log_level="warning")
```

- [ ] **Step 3: Add CLI subcommand**

Append to `speechtotext/cli.py`:

```python
@app.command()
def serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int | None, typer.Option("--port")] = None,
) -> None:
    """Run the LocalLexis HTTP API."""
    from speechtotext.api.server import run as _run
    _run(host=host, port=port)
```

- [ ] **Step 4: Run + commit**

```bash
pytest tests/api/test_server.py -v
# manual smoke:
stt serve --port 8765 &  # then curl http://127.0.0.1:8765/health
git add speechtotext tests/api/test_server.py
git commit -m "feat(cli): 'stt serve' starts the LocalLexis HTTP API"
```

---

# Milestone 2 — Packaging

### Task 12: PyInstaller spec for the sidecar binary

**Files:**
- Create: `packaging/locallexis-sidecar.spec`
- Create: `packaging/README.md`
- Modify: `pyproject.toml` (add packaging extra)

- [ ] **Step 1: Add PyInstaller to a packaging extra**

Edit `pyproject.toml`:

```toml
packaging = [
    "pyinstaller>=6.0",
]
```

Run: `pip install -e ".[packaging]"`

- [ ] **Step 2: Write spec file**

`packaging/locallexis-sidecar.spec`:

```python
# PyInstaller spec for the LocalLexis FastAPI sidecar.
# Build:   pyinstaller packaging/locallexis-sidecar.spec --clean
# Output:  dist/locallexis-sidecar (or .exe on Windows)
# The Tauri shell ships this binary alongside the app.

a = Analysis(
    ['../speechtotext/api/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'speechtotext.asr.faster_whisper',
        'speechtotext.diarize.pyannote',
        'uvicorn.logging',
    ],
    hookspath=[],
    excludes=['matplotlib', 'tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name='locallexis-sidecar',
    debug=False,
    strip=False,
    upx=False,
    console=True,
)
```

- [ ] **Step 3: Create `__main__.py` entrypoint**

`speechtotext/api/__main__.py`:

```python
from speechtotext.api.server import run

if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Document build**

`packaging/README.md`:

```markdown
# LocalLexis sidecar packaging

Build the FastAPI sidecar as a standalone binary:

    pip install -e ".[api,packaging]"
    pyinstaller packaging/locallexis-sidecar.spec --clean

Output: `dist/locallexis-sidecar` (Linux/macOS) or `dist/locallexis-sidecar.exe` (Windows).

Note: pyannote + torch are heavy. Expect 600–900 MB.
Run a smoke test:

    ./dist/locallexis-sidecar &
    curl http://127.0.0.1:<port>/health    # port comes from the JSON handshake
```

- [ ] **Step 5: Local smoke + commit**

```bash
pyinstaller packaging/locallexis-sidecar.spec --clean
./dist/locallexis-sidecar &
SIDECAR_PID=$!
sleep 2
# Read the JSON handshake from stdout to find the port (this step manual for now)
kill $SIDECAR_PID
git add packaging speechtotext/api/__main__.py pyproject.toml
git commit -m "build: PyInstaller spec for LocalLexis sidecar binary"
```

---

### Task 13: CI matrix — Linux + macOS + Windows builds

**Files:**
- Create: `.github/workflows/build-sidecar.yml`

- [ ] **Step 1: Workflow**

```yaml
name: build-sidecar
on:
  push:
    branches: [main]
  pull_request:
jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-14, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - name: Install ffmpeg (Linux)
        if: runner.os == 'Linux'
        run: sudo apt-get update && sudo apt-get install -y ffmpeg
      - name: Install ffmpeg (macOS)
        if: runner.os == 'macOS'
        run: brew install ffmpeg
      - name: Install ffmpeg (Windows)
        if: runner.os == 'Windows'
        run: choco install -y ffmpeg
      - run: pip install -e ".[api,packaging,dev]"
      - run: pytest -m "not integration"
      - run: pyinstaller packaging/locallexis-sidecar.spec --clean
      - uses: actions/upload-artifact@v4
        with:
          name: locallexis-sidecar-${{ runner.os }}
          path: dist/locallexis-sidecar*
```

- [ ] **Step 2: Push branch, verify all three runners succeed, then commit on main**

```bash
git checkout -b ci/build-sidecar
git add .github/workflows/build-sidecar.yml
git commit -m "ci: build sidecar on Linux/macOS/Windows"
git push -u origin ci/build-sidecar
# wait for green run, then merge
```

---

# Milestone 3 — Frontend scaffold

### Task 14: Initialize Tauri + Vite + React + TypeScript project

**Files:**
- Create: `ui/` (whole subtree)

- [ ] **Step 1: Install Rust + Tauri CLI prerequisites**

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"
cargo install create-tauri-app --locked
```

- [ ] **Step 2: Scaffold**

From the project root:

```bash
cd /Users/lieuwejongsma/SpeechToText
cargo create-tauri-app --manager pnpm --template react-ts --identifier dev.locallexis.app --name locallexis ui
cd ui && pnpm install
```

- [ ] **Step 3: Verify dev mode launches**

```bash
cd ui && pnpm tauri dev
```

Expected: a window opens with the default Tauri+React template. Quit it.

- [ ] **Step 4: Strip the template down to an empty App shell**

Edit `ui/src/App.tsx` to:

```tsx
import './styles/global.css';

export default function App() {
  return <div className="stage">LocalLexis</div>;
}
```

Edit `ui/src/main.tsx`:

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(<App />);
```

Create empty `ui/src/styles/global.css` and `ui/src/styles/tokens.css`.

Delete the default `App.css`, `assets/`, and any unused boilerplate.

- [ ] **Step 5: Commit**

```bash
cd /Users/lieuwejongsma/SpeechToText
git add ui/
git commit -m "feat(ui): scaffold Tauri + Vite + React + TS, strip template"
```

---

### Task 15: Port design tokens + load fonts

**Files:**
- Modify: `ui/src/styles/tokens.css`
- Modify: `ui/src/styles/global.css`
- Modify: `ui/index.html`

- [ ] **Step 1: Tokens**

Copy `:root { ... }` block from [docs/design_handoff_locallexis/styles.css](../../design_handoff_locallexis/styles.css) lines 1–39 into `ui/src/styles/tokens.css` verbatim.

- [ ] **Step 2: Global**

Copy the `* { box-sizing }` reset and `html, body { ... }` rules (lines 41–71 of handoff styles.css) into `ui/src/styles/global.css`. Also `import './tokens.css';` at the top.

- [ ] **Step 3: Fonts**

Edit `ui/index.html` head:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300..700;1,6..72,300..700&family=Geist:wght@300..700&family=Geist+Mono:wght@300..600&display=swap">
```

- [ ] **Step 4: Verify**

```bash
cd ui && pnpm tauri dev
```

The "LocalLexis" text should render in Geist on a dark `#050506` page.

- [ ] **Step 5: Commit**

```bash
git add ui/
git commit -m "feat(ui): design tokens (dark manuscript palette) + Newsreader/Geist fonts"
```

---

### Task 16: Tauri sidecar lifecycle — launch/kill the PyInstaller binary

**Files:**
- Modify: `ui/src-tauri/Cargo.toml`
- Modify: `ui/src-tauri/tauri.conf.json`
- Modify: `ui/src-tauri/src/main.rs`
- Create: `ui/src-tauri/src/sidecar.rs`
- Create: `ui/src/api/client.ts`

- [ ] **Step 1: Cargo dependencies**

Edit `ui/src-tauri/Cargo.toml` `[dependencies]`:

```toml
tauri = { version = "2", features = ["protocol-asset"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
```

- [ ] **Step 2: Bundle sidecar binary**

Place the built `locallexis-sidecar` binary at `ui/src-tauri/binaries/locallexis-sidecar-<target-triple>` (e.g. `aarch64-apple-darwin`). Edit `ui/src-tauri/tauri.conf.json` `tauri.bundle.externalBin`:

```json
"externalBin": ["binaries/locallexis-sidecar"]
```

- [ ] **Step 3: Sidecar manager (Rust)**

`ui/src-tauri/src/sidecar.rs`:

```rust
use std::io::{BufRead, BufReader};
use std::sync::Mutex;
use tauri::api::process::{Command, CommandEvent};

pub struct SidecarUrl(pub Mutex<Option<String>>);

#[tauri::command]
pub fn sidecar_url(state: tauri::State<SidecarUrl>) -> Option<String> {
    state.0.lock().unwrap().clone()
}

pub fn spawn(app: &tauri::AppHandle) -> Result<(), String> {
    let (mut rx, _child) = Command::new_sidecar("locallexis-sidecar")
        .map_err(|e| e.to_string())?
        .spawn()
        .map_err(|e| e.to_string())?;
    let state: tauri::State<SidecarUrl> = app.state();
    let url = state.0.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            if let CommandEvent::Stdout(line) = event {
                if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&line) {
                    if let Some(p) = parsed.get("locallexis").and_then(|v| v.get("port")).and_then(|v| v.as_u64()) {
                        *url.lock().unwrap() = Some(format!("http://127.0.0.1:{}", p));
                    }
                }
            }
        }
    });
    Ok(())
}
```

- [ ] **Step 4: Wire into main.rs**

```rust
mod sidecar;

fn main() {
    tauri::Builder::default()
        .manage(sidecar::SidecarUrl(Default::default()))
        .invoke_handler(tauri::generate_handler![sidecar::sidecar_url])
        .setup(|app| {
            sidecar::spawn(&app.handle()).expect("failed to start sidecar");
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [ ] **Step 5: Frontend API client**

`ui/src/api/client.ts`:

```ts
import { invoke } from '@tauri-apps/api/core';

let cached: string | null = null;

export async function baseUrl(): Promise<string> {
  if (cached) return cached;
  for (let i = 0; i < 50; i++) {
    const u = (await invoke('sidecar_url')) as string | null;
    if (u) { cached = u; return u; }
    await new Promise(r => setTimeout(r, 100));
  }
  throw new Error('sidecar did not start within 5 seconds');
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const u = await baseUrl();
  const r = await fetch(u + path, init);
  if (!r.ok) throw new Error(`${r.status} ${path}: ${await r.text()}`);
  return r.json() as Promise<T>;
}
```

- [ ] **Step 6: Smoke**

```bash
cd ui && pnpm tauri dev
```

In the dev console: `window.__TAURI__.core.invoke('sidecar_url')` should resolve to `http://127.0.0.1:<port>` within a few seconds. `fetch('<url>/health').then(r => r.json())` should return `{ok: true}`.

- [ ] **Step 7: Commit**

```bash
git add ui/
git commit -m "feat(ui): bundle + launch PyInstaller sidecar from Tauri shell"
```

---

### Task 17: API DTO types + SSE helper

**Files:**
- Create: `ui/src/api/types.ts`
- Create: `ui/src/api/sse.ts`

- [ ] **Step 1: Types**

`ui/src/api/types.ts`:

```ts
export type JobStatus = 'pending' | 'running' | 'complete' | 'failed';

export interface JobRecord {
  id: string;
  kind: 'transcribe' | 'record';
  status: JobStatus;
  stage: string;
  percent: number;
  error: string | null;
  transcript_id: string | null;
  audio_path: string | null;
  paths: Record<string, string>;
}

export type SseEvent =
  | { type: 'stage'; stage: string; percent: number }
  | { type: 'line'; speaker: string; ts: number; text: string }
  | { type: 'complete'; transcript_id: string; paths: Record<string, string> }
  | { type: 'error'; message: string };

export interface TranscriptListItem {
  id: string;
  path: string;
  audio_path?: string;
  duration_seconds?: number;
  language?: string;
  speakers?: number;
  created_at?: string;
  models?: Record<string, string>;
  error?: string;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  speaker: string;
  text: string;
}

export interface TranscriptDoc {
  version: number;
  audio_path: string;
  duration_seconds: number;
  language: string;
  speakers: Record<string, string>;
  segments: TranscriptSegment[];
  models: Record<string, string>;
  created_at: string;
}

export interface AudioDeviceDto {
  index: number;
  name: string;
  channels: number;
  sample_rate: number;
  default: boolean;
  hint: 'mic' | 'loopback' | 'mic+loopback' | 'unknown';
}

export interface ConfigDto {
  backend: 'auto' | 'cpu' | 'cuda' | 'mps';
  asr_model: string;
  hf_token_set: boolean;
  model_cache_dir: string;
  default_out_dir: string | null;
  watch: { recursive: boolean; debounce_seconds: number; extensions: string[] };
}
```

- [ ] **Step 2: SSE subscription**

`ui/src/api/sse.ts`:

```ts
import { baseUrl } from './client';
import type { SseEvent } from './types';

export async function subscribeJob(jobId: string, onEvent: (e: SseEvent) => void, signal?: AbortSignal): Promise<void> {
  const url = (await baseUrl()) + `/jobs/${jobId}/stream`;
  const resp = await fetch(url, { signal });
  if (!resp.ok || !resp.body) throw new Error(`SSE ${resp.status}`);
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) return;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const data = chunk
        .split('\n')
        .filter(l => l.startsWith('data: '))
        .map(l => l.slice(6))
        .join('');
      if (!data) continue;
      try { onEvent(JSON.parse(data) as SseEvent); } catch {}
    }
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add ui/src/api
git commit -m "feat(ui): API DTO types + SSE subscription helper"
```

---

### Task 18: Stores — Zustand-based job/transcript/config/recording state

Use Zustand (small, no boilerplate, plays well with React 18). One store per spec section.

**Files:**
- Modify: `ui/package.json`
- Create: `ui/src/stores/jobs.ts`
- Create: `ui/src/stores/transcripts.ts`
- Create: `ui/src/stores/library.ts`
- Create: `ui/src/stores/recording.ts`
- Create: `ui/src/stores/config.ts`

- [ ] **Step 1: Install Zustand**

```bash
cd ui && pnpm add zustand
```

- [ ] **Step 2: Jobs store**

`ui/src/stores/jobs.ts`:

```ts
import { create } from 'zustand';
import { api } from '../api/client';
import { subscribeJob } from '../api/sse';
import type { JobRecord, SseEvent } from '../api/types';

interface JobView {
  id: string;
  status: 'pending' | 'running' | 'complete' | 'failed';
  stage: string;
  percent: number;
  lines: { speaker: string; ts: number; text: string }[];
  error: string | null;
  paths: Record<string, string>;
}

interface JobsState {
  byId: Record<string, JobView>;
  start: (jobId: string) => void;
}

export const useJobs = create<JobsState>((set, get) => ({
  byId: {},
  start: (jobId) => {
    set(s => ({ byId: { ...s.byId, [jobId]: { id: jobId, status: 'pending', stage: '', percent: 0, lines: [], error: null, paths: {} } } }));
    const apply = (mut: (v: JobView) => JobView) =>
      set(s => ({ byId: { ...s.byId, [jobId]: mut(s.byId[jobId]) } }));
    subscribeJob(jobId, (ev: SseEvent) => {
      if (ev.type === 'stage') apply(v => ({ ...v, status: 'running', stage: ev.stage, percent: ev.percent }));
      else if (ev.type === 'line') apply(v => ({ ...v, lines: [...v.lines, { speaker: ev.speaker, ts: ev.ts, text: ev.text }] }));
      else if (ev.type === 'complete') apply(v => ({ ...v, status: 'complete', paths: ev.paths }));
      else if (ev.type === 'error') apply(v => ({ ...v, status: 'failed', error: ev.message }));
    }).catch(err => apply(v => ({ ...v, status: 'failed', error: String(err) })));
  },
}));

export async function startTranscribe(path: string, opts: { language?: string; num_speakers?: number; backend?: string } = {}): Promise<string> {
  const { job_id } = await api<{ job_id: string }>('/jobs/transcribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, ...opts }),
  });
  useJobs.getState().start(job_id);
  return job_id;
}

export async function startRecord(out: string, device?: string): Promise<string> {
  const { job_id } = await api<{ job_id: string }>('/jobs/record', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ out, device }),
  });
  useJobs.getState().start(job_id);
  return job_id;
}

export async function stopRecord(jobId: string): Promise<void> {
  await api(`/jobs/${jobId}/stop`, { method: 'POST' });
}

export async function fetchJob(jobId: string): Promise<JobRecord> {
  return api<JobRecord>(`/jobs/${jobId}`);
}
```

- [ ] **Step 3: Transcripts + library + config + recording stores**

`ui/src/stores/transcripts.ts`:

```ts
import { create } from 'zustand';
import { api } from '../api/client';
import type { TranscriptDoc } from '../api/types';

interface State {
  byId: Record<string, TranscriptDoc>;
  load: (id: string) => Promise<TranscriptDoc>;
  relabel: (id: string, mapping: Record<string, string>) => Promise<void>;
}

export const useTranscripts = create<State>((set, get) => ({
  byId: {},
  load: async (id) => {
    const doc = await api<TranscriptDoc>(`/transcripts/${id}`);
    set(s => ({ byId: { ...s.byId, [id]: doc } }));
    return doc;
  },
  relabel: async (id, mapping) => {
    await api(`/transcripts/${id}/relabel`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(mapping),
    });
    await get().load(id);
  },
}));
```

`ui/src/stores/library.ts`:

```ts
import { create } from 'zustand';
import { api } from '../api/client';
import type { TranscriptListItem } from '../api/types';

interface State {
  items: TranscriptListItem[];
  refresh: () => Promise<void>;
}

export const useLibrary = create<State>((set) => ({
  items: [],
  refresh: async () => set({ items: await api<TranscriptListItem[]>('/transcripts') }),
}));
```

`ui/src/stores/config.ts`:

```ts
import { create } from 'zustand';
import { api } from '../api/client';
import type { ConfigDto } from '../api/types';

interface State {
  cfg: ConfigDto | null;
  load: () => Promise<void>;
  patch: (updates: Partial<ConfigDto> & { hf_token?: string }) => Promise<void>;
}

export const useConfig = create<State>((set) => ({
  cfg: null,
  load: async () => set({ cfg: await api<ConfigDto>('/config') }),
  patch: async (updates) => {
    const cfg = await api<ConfigDto>('/config', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    set({ cfg });
  },
}));
```

`ui/src/stores/recording.ts`:

```ts
import { create } from 'zustand';

interface State {
  jobId: string | null;
  active: boolean;
  paused: boolean;
  elapsed: number;          // seconds
  deviceId: string | null;
  setJob: (id: string | null) => void;
  setActive: (v: boolean) => void;
  setPaused: (v: boolean) => void;
  tick: (delta: number) => void;
  reset: () => void;
  setDevice: (id: string | null) => void;
}

export const useRecording = create<State>((set) => ({
  jobId: null, active: false, paused: false, elapsed: 0, deviceId: null,
  setJob: (id) => set({ jobId: id }),
  setActive: (v) => set({ active: v }),
  setPaused: (v) => set({ paused: v }),
  tick: (delta) => set(s => ({ elapsed: s.elapsed + delta })),
  reset: () => set({ jobId: null, active: false, paused: false, elapsed: 0 }),
  setDevice: (id) => set({ deviceId: id }),
}));
```

- [ ] **Step 4: Commit**

```bash
git add ui/
git commit -m "feat(ui): zustand stores for jobs, transcripts, library, config, recording"
```

---

# Milestone 4 — Chrome

### Task 19: Icon primitive

Port handoff `primitives.jsx` to TSX with full prop types and all icon names.

**Files:**
- Create: `ui/src/primitives/Icon.tsx`
- Create: `ui/src/primitives/colors.ts`
- Create: `ui/src/primitives/Icon.test.tsx`
- Modify: `ui/package.json` (add Vitest + RTL)

- [ ] **Step 1: Install test deps**

```bash
cd ui && pnpm add -D vitest @testing-library/react @testing-library/jest-dom jsdom @vitejs/plugin-react
```

Edit `ui/vite.config.ts` to add:

```ts
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test-setup.ts'] },
});
```

Create `ui/src/test-setup.ts`:

```ts
import '@testing-library/jest-dom/vitest';
```

Edit `ui/package.json` scripts:

```json
"test": "vitest"
```

- [ ] **Step 2: Test**

`ui/src/primitives/Icon.test.tsx`:

```tsx
import { render } from '@testing-library/react';
import { Icon } from './Icon';

test('renders an svg with the given size', () => {
  const { container } = render(<Icon name="lock" size={20} />);
  const svg = container.querySelector('svg')!;
  expect(svg.getAttribute('width')).toBe('20');
});

test('unknown icon name renders nothing', () => {
  const { container } = render(<Icon name={'nope' as never} />);
  expect(container.querySelector('svg')).toBeNull();
});
```

- [ ] **Step 3: Implement**

`ui/src/primitives/colors.ts`:

```ts
export const SPEAKER_COLORS = ['#6fd99a', '#e8b169', '#7aa5e8', '#d97e94', '#c2a3e8'] as const;
```

`ui/src/primitives/Icon.tsx`: port the `switch (name)` body from [docs/design_handoff_locallexis/primitives.jsx](../../design_handoff_locallexis/primitives.jsx) verbatim, adapted to TS:

```tsx
export type IconName =
  | 'plus' | 'transcribe' | 'mic' | 'eye' | 'folder' | 'book' | 'gear'
  | 'upload' | 'chev' | 'copy' | 'doc' | 'braces' | 'wave' | 'shield'
  | 'lock' | 'sparkle' | 'pause' | 'check' | 'search';

export function Icon({ name, size = 16, stroke = 1.5 }: { name: IconName; size?: number; stroke?: number }) {
  const s = { width: size, height: size, fill: 'none', stroke: 'currentColor', strokeWidth: stroke, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  switch (name) {
    case 'plus':       return <svg viewBox="0 0 16 16" {...s}><path d="M8 3v10M3 8h10"/></svg>;
    case 'transcribe': return <svg viewBox="0 0 16 16" {...s}><path d="M3 4h7M3 8h10M3 12h6"/></svg>;
    case 'mic':        return <svg viewBox="0 0 16 16" {...s}><rect x="6" y="2" width="4" height="8" rx="2"/><path d="M3.5 8a4.5 4.5 0 009 0M8 12.5V14"/></svg>;
    case 'eye':        return <svg viewBox="0 0 16 16" {...s}><path d="M1.5 8C3 4.5 5.5 3 8 3s5 1.5 6.5 5c-1.5 3.5-4 5-6.5 5S3 11.5 1.5 8z"/><circle cx="8" cy="8" r="2"/></svg>;
    case 'folder':     return <svg viewBox="0 0 16 16" {...s}><path d="M2 4.5A1.5 1.5 0 013.5 3h2.8l1.4 1.5h4.8A1.5 1.5 0 0114 6v5.5A1.5 1.5 0 0112.5 13h-9A1.5 1.5 0 012 11.5v-7z"/></svg>;
    case 'book':       return <svg viewBox="0 0 16 16" {...s}><path d="M3 3h4a2 2 0 012 2v8a2 2 0 00-2-2H3V3zM13 3H9a2 2 0 00-2 2v8a2 2 0 012-2h4V3z"/></svg>;
    case 'gear':       return <svg viewBox="0 0 16 16" {...s}><circle cx="8" cy="8" r="2"/><path d="M8 1v2M8 13v2M3.5 3.5l1.4 1.4M11.1 11.1l1.4 1.4M1 8h2M13 8h2M3.5 12.5l1.4-1.4M11.1 4.9l1.4-1.4"/></svg>;
    case 'upload':     return <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"><path d="M12 16V4M7 9l5-5 5 5M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>;
    case 'chev':       return <svg viewBox="0 0 16 16" {...s}><path d="M6 4l4 4-4 4"/></svg>;
    case 'copy':       return <svg viewBox="0 0 16 16" {...s}><rect x="5" y="5" width="9" height="9" rx="1.5"/><path d="M3 11V3a1 1 0 011-1h7"/></svg>;
    case 'doc':        return <svg viewBox="0 0 16 16" {...s}><path d="M3.5 2h6L13 5.5v8A1.5 1.5 0 0111.5 15h-8A1.5 1.5 0 012 13.5v-10A1.5 1.5 0 013.5 2z"/><path d="M9 2v4h4"/></svg>;
    case 'braces':     return <svg viewBox="0 0 16 16" {...s}><path d="M5.5 2.5C4 2.5 4 4 4 5s0 2.5-2 2.5C4 8 4 9.5 4 10.5s0 2.5 1.5 2.5"/><path d="M10.5 2.5C12 2.5 12 4 12 5s0 2.5 2 2.5c-2 .5-2 2-2 3s0 2.5-1.5 2.5"/></svg>;
    case 'wave':       return <svg viewBox="0 0 16 16" {...s}><path d="M2 8h1M5 5v6M8 3v10M11 5v6M13 8h1"/></svg>;
    case 'shield':     return <svg viewBox="0 0 16 16" {...s}><path d="M8 1.5l5 1.5v4.5c0 3-2 5.5-5 6.5-3-1-5-3.5-5-6.5V3l5-1.5z"/></svg>;
    case 'lock':       return <svg viewBox="0 0 16 16" {...s}><rect x="3" y="7" width="10" height="7" rx="1.5"/><path d="M5.5 7V5a2.5 2.5 0 015 0v2"/></svg>;
    case 'sparkle':    return <svg viewBox="0 0 16 16" {...s}><path d="M8 2v3M8 11v3M2 8h3M11 8h3M4 4l2 2M10 10l2 2M12 4l-2 2M6 10l-2 2"/></svg>;
    case 'pause':      return <svg viewBox="0 0 16 16" {...s}><rect x="4.5" y="3.5" width="2.5" height="9" rx="0.5"/><rect x="9" y="3.5" width="2.5" height="9" rx="0.5"/></svg>;
    case 'check':      return <svg viewBox="0 0 16 16" {...s}><path d="M3 8.5l3.2 3.2L13 5"/></svg>;
    case 'search':     return <svg viewBox="0 0 16 16" {...s}><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/></svg>;
    default:           return null;
  }
}
```

- [ ] **Step 4: Run + commit**

```bash
cd ui && pnpm test --run
git add ui/
git commit -m "feat(ui): Icon primitive + SPEAKER_COLORS palette"
```

---

### Task 20: Sidebar + window chrome

Recreate the handoff sidebar (brand, +New, nav, Recent, footer) and the macOS-style window with titlebar. Use a top-level router state (string union).

**Files:**
- Create: `ui/src/chrome/Window.tsx`
- Create: `ui/src/chrome/Sidebar.tsx`
- Modify: `ui/src/styles/global.css` (port sidebar+window CSS)
- Modify: `ui/src/App.tsx`

- [ ] **Step 1: Port sidebar+window CSS**

Append to `ui/src/styles/global.css` the relevant blocks from [docs/design_handoff_locallexis/styles.css](../../design_handoff_locallexis/styles.css):
- `.stage`, `.window`, `.titlebar` and child rules (lines ~73–127)
- `.app`, `.sidebar`, `.brand`, `.new-btn`, `.nav`, `.nav-item`, `.section-label`, `.recent-list`, `.recent-item`, `.sidebar-footer` (lines ~128–293)
- `.main`, `.main-header`, `.chip`, `.main-body` (lines ~295–352)
- `@keyframes pulse`

Copy verbatim — these are the spec.

- [ ] **Step 2: Route type**

`ui/src/types/route.ts`:

```ts
export type Route = 'idle' | 'progress' | 'complete' | 'record' | 'library' | 'watch' | 'settings';
```

- [ ] **Step 3: Sidebar component**

`ui/src/chrome/Sidebar.tsx`: adapt [docs/design_handoff_locallexis/sidebar.jsx](../../design_handoff_locallexis/sidebar.jsx) to TSX. Replace mock data with `useLibrary` recent items (slice top 5) and the `useRecording` `active` flag for the Record nav `.live-dot`. Click on a recent item should `setRoute('complete')` and load that transcript via the `useTranscripts` store.

```tsx
import { Icon, type IconName } from '../primitives/Icon';
import { useLibrary } from '../stores/library';
import { useRecording } from '../stores/recording';
import { useTranscripts } from '../stores/transcripts';
import type { Route } from '../types/route';

const NAV: { id: Route; label: string; icon: IconName }[] = [
  { id: 'idle',     label: 'Transcribe',  icon: 'transcribe' },
  { id: 'record',   label: 'Record',      icon: 'mic' },
  { id: 'watch',    label: 'Watch folder',icon: 'eye' },
  { id: 'library',  label: 'Library',     icon: 'book' },
  { id: 'settings', label: 'Settings',    icon: 'gear' },
];

export function Sidebar({ route, setRoute, currentTranscriptId, setCurrentTranscriptId }: {
  route: Route;
  setRoute: (r: Route) => void;
  currentTranscriptId: string | null;
  setCurrentTranscriptId: (id: string | null) => void;
}) {
  const recent = useLibrary(s => s.items.slice(0, 5));
  const recording = useRecording(s => s.active);
  const loadTranscript = useTranscripts(s => s.load);

  return (
    <div className="sidebar">
      <div className="brand">
        <div className="wordmark">LocalLexis</div>
        <div className="pron">/ˈloʊkəlˌlɛksɪs/ &nbsp;·&nbsp; v1.0</div>
      </div>
      <button className="new-btn" onClick={() => setRoute('idle')}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <Icon name="plus" size={13} stroke={1.8} /> New transcription
        </span>
        <span className="kbd">⌘N</span>
      </button>
      <div className="nav">
        {NAV.map(n => {
          const active = route === n.id || (n.id === 'idle' && (route === 'complete' || route === 'progress'));
          return (
            <div key={n.id} className={'nav-item' + (active ? ' active' : '')} onClick={() => setRoute(n.id)}>
              <span className="icon"><Icon name={n.icon} size={15} /></span>
              <span>{n.label}</span>
              {n.id === 'record' && recording ? <span className="live-dot" /> : null}
            </div>
          );
        })}
      </div>
      <div className="section-label">Recent</div>
      <div className="recent-list">
        {recent.map(r => (
          <div key={r.id} className="recent-item"
               onClick={async () => { await loadTranscript(r.id); setCurrentTranscriptId(r.id); setRoute('complete'); }}>
            <span>{r.audio_path?.split('/').pop() || r.id}</span>
            <span className="meta">
              <span>{r.duration_seconds ? fmt(r.duration_seconds) : '—'}</span>
            </span>
          </div>
        ))}
      </div>
      <div className="sidebar-footer">
        <span className="on-device">All processing on-device</span>
      </div>
    </div>
  );
}

function fmt(secs: number) {
  const m = Math.floor(secs / 60); const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}
```

- [ ] **Step 4: Window chrome**

`ui/src/chrome/Window.tsx`:

```tsx
import { ReactNode } from 'react';

export function Window({ children, screenLabel }: { children: ReactNode; screenLabel: string }) {
  return (
    <div className="stage">
      <div className="window chrome-macos" data-screen-label={screenLabel}>
        <div className="titlebar">
          <div className="tl">
            <span className="dot r" /><span className="dot y" /><span className="dot g" />
          </div>
          <div className="titlebar-title">LocalLexis</div>
        </div>
        <div className="app">{children}</div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Update App.tsx**

```tsx
import { useState, useEffect } from 'react';
import './styles/global.css';
import { Window } from './chrome/Window';
import { Sidebar } from './chrome/Sidebar';
import { useLibrary } from './stores/library';
import type { Route } from './types/route';

export default function App() {
  const [route, setRoute] = useState<Route>('idle');
  const [tid, setTid] = useState<string | null>(null);
  const refreshLibrary = useLibrary(s => s.refresh);

  useEffect(() => { refreshLibrary().catch(() => {}); }, [refreshLibrary]);

  return (
    <Window screenLabel={route}>
      <Sidebar route={route} setRoute={setRoute} currentTranscriptId={tid} setCurrentTranscriptId={setTid} />
      <div className="main">
        <div className="main-header"><span className="title">{route}</span></div>
        <div className="main-body"><pre>{route}</pre></div>
      </div>
    </Window>
  );
}
```

- [ ] **Step 6: Smoke + commit**

```bash
cd ui && pnpm tauri dev
# verify: sidebar renders correctly, click between nav items
git add ui/
git commit -m "feat(ui): sidebar + window chrome (high-fi from handoff)"
```

---

### Task 21: Main header with chips

**Files:**
- Create: `ui/src/chrome/MainHeader.tsx`
- Modify: `ui/src/App.tsx`

- [ ] **Step 1: Component**

`ui/src/chrome/MainHeader.tsx`:

```tsx
import { Icon } from '../primitives/Icon';
import type { Route } from '../types/route';

const HEADERS: Record<Route, { crumb: string; title: string }> = {
  idle:     { crumb: 'New transcription', title: 'Transcribe' },
  progress: { crumb: 'Transcribing',      title: 'Transcribe' },
  complete: { crumb: 'Transcript',        title: 'Transcript' },
  record:   { crumb: 'Recording',         title: 'Record' },
  library:  { crumb: 'Library',           title: 'All transcripts' },
  watch:    { crumb: 'Watch folder',      title: 'Watch folder' },
  settings: { crumb: 'Settings',          title: 'Settings' },
};

export function MainHeader({ route, doneLabel, isLive }: { route: Route; doneLabel?: string; isLive?: boolean }) {
  const h = HEADERS[route];
  return (
    <div className="main-header">
      <span className="crumb">{h.crumb}</span>
      <span className="title">{h.title}</span>
      <span className="spacer" />
      {route === 'complete' && doneLabel && (
        <span className="chip"><Icon name="check" size={11} stroke={2} /> {doneLabel}</span>
      )}
      {route === 'record' && isLive && (
        <span className="chip accent"><span className="dot" /> Live</span>
      )}
      <span className="chip"><Icon name="lock" size={11} stroke={1.5} /> On-device</span>
    </div>
  );
}
```

- [ ] **Step 2: Wire into App.tsx**

Replace the placeholder `.main-header` with `<MainHeader route={route} />`.

- [ ] **Step 3: Commit**

```bash
git add ui/
git commit -m "feat(ui): main header with crumb, title, On-device chip"
```

---

# Milestone 5 — Idle screen

### Task 22: Idle screen — high-fi

Port [docs/design_handoff_locallexis/screens.jsx](../../design_handoff_locallexis/screens.jsx) `IdleScreen` to TSX. Wire drop + Browse to actual file ingestion.

**Files:**
- Create: `ui/src/screens/IdleScreen.tsx`
- Create: `ui/src/screens/IdleScreen.test.tsx`
- Modify: `ui/src/styles/global.css` (port `.idle`, `.hero`, `.drop`, `.options-row`, `.recent-files`, `.etymology` from handoff)
- Modify: `ui/src/App.tsx`

- [ ] **Step 1: Port styles**

Append to `ui/src/styles/global.css` lines ~354–497 of handoff `styles.css` (IDLE section + etymology).

- [ ] **Step 2: Test**

`ui/src/screens/IdleScreen.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { IdleScreen } from './IdleScreen';

test('dropping a file calls onTranscribe with the path', () => {
  const onTranscribe = vi.fn();
  render(<IdleScreen onTranscribe={onTranscribe} recentFiles={[]} />);
  const drop = screen.getByText(/Drag an audio file/).closest('.drop')!;
  const file = new File(['x'], 'meet.mp3', { type: 'audio/mpeg' });
  // jsdom: File has no `.path`. Override:
  Object.defineProperty(file, 'path', { value: '/tmp/meet.mp3' });
  fireEvent.drop(drop, { dataTransfer: { files: [file] } });
  expect(onTranscribe).toHaveBeenCalledWith('/tmp/meet.mp3');
});

test('drag-over toggles active class', () => {
  render(<IdleScreen onTranscribe={() => {}} recentFiles={[]} />);
  const drop = screen.getByText(/Drag an audio file/).closest('.drop') as HTMLElement;
  fireEvent.dragEnter(drop);
  expect(drop.classList.contains('active')).toBe(true);
  fireEvent.dragLeave(drop);
  expect(drop.classList.contains('active')).toBe(false);
});
```

- [ ] **Step 3: Implement**

`ui/src/screens/IdleScreen.tsx`: port [screens.jsx#L6–77](../../design_handoff_locallexis/screens.jsx) verbatim, then:
- Replace `setRoute('complete')` with `props.onTranscribe(filePath)`.
- File path comes from Tauri's drag event (use `@tauri-apps/api/event` `listen('tauri://file-drop', ...)`) — in browser tests fall back to `e.dataTransfer.files[0].path`.
- "Browse files…" calls Tauri's `@tauri-apps/plugin-dialog` `open({ multiple: false, filters: [{ name: 'Audio', extensions: ['mp3','m4a','wav','ogg','flac','webm']}] })`.
- Recent files list reads from `props.recentFiles`.

(Full component code follows the handoff structure — 60–80 lines.)

- [ ] **Step 4: Wire into App.tsx**

```tsx
import { IdleScreen } from './screens/IdleScreen';
import { startTranscribe } from './stores/jobs';

// inside .main-body:
{route === 'idle' && (
  <IdleScreen
    recentFiles={useLibrary(s => s.items.slice(0, 3))}
    onTranscribe={async (path) => {
      const id = await startTranscribe(path);
      setCurrentJobId(id);
      setRoute('progress');
    }}
  />
)}
```

Add `const [currentJobId, setCurrentJobId] = useState<string | null>(null);` at top of App.

- [ ] **Step 5: Smoke + commit**

```bash
cd ui && pnpm test --run
cd ui && pnpm tauri dev
# verify: hero renders, drop a file, observe navigation to (placeholder) progress route
git add ui/
git commit -m "feat(ui): Idle screen (high-fi) — drop zone, options, recent, etymology"
```

---

# Milestone 6 — In-progress design + screen

### Task 23: Design note — in-progress screen

The handoff doesn't include this screen. Design it before building.

**Files:**
- Create: `docs/design_handoff_locallexis/progress-screen.md`

- [ ] **Step 1: Write the design note**

Include: layout (top progress strip + stage chips row + scrolling live transcript area), copy ("Transcribing meeting-05-15.mp3 · 42 MB · 1h 04m"), stage chip states (`pending | active | done`), color use (active chip uses `--accent`, done uses `--ink-muted`, pending uses `--ink-dim`), typography (reuse `.transcript .turn` typography for streaming lines), and where the cancel button goes (top-right, in main-header as a small icon-btn). State that final layout follows the same `max-width: 920px` container as the Complete screen so the visual transition into Complete is seamless.

Length target: ~300 words, with a small ASCII wireframe.

- [ ] **Step 2: Commit**

```bash
git add docs/design_handoff_locallexis/progress-screen.md
git commit -m "design: in-progress screen layout note"
```

---

### Task 24: Progress screen — implementation

**Files:**
- Create: `ui/src/screens/ProgressScreen.tsx`
- Modify: `ui/src/styles/global.css` (append `.progress` styles)
- Modify: `ui/src/App.tsx`

- [ ] **Step 1: Styles**

Append to `ui/src/styles/global.css`:

```css
.progress {
  max-width: 920px; margin: 0 auto; padding: 36px 40px 80px;
  display: flex; flex-direction: column; gap: 22px;
}
.progress .doc-head { display: flex; flex-direction: column; gap: 8px; padding-bottom: 22px; border-bottom: 0.5px solid var(--line); }
.progress .doc-head .file-meta { font-family: var(--mono); font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink-dim); }
.progress .doc-head h1 { font-family: var(--serif); font-size: 28px; font-weight: 400; letter-spacing: -0.012em; margin: 0; color: var(--ink); }
.progress .bar { height: 4px; background: var(--bg-elev); border-radius: 2px; overflow: hidden; }
.progress .bar > div { height: 100%; background: var(--accent); transition: width 0.3s; }
.progress .stages { display: flex; gap: 8px; flex-wrap: wrap; }
.progress .stage-chip {
  font-family: var(--mono); font-size: 11.5px; letter-spacing: 0.04em;
  height: 24px; padding: 0 9px; border-radius: 999px;
  background: var(--bg-elev); border: 0.5px solid var(--line); color: var(--ink-dim);
  display: inline-flex; align-items: center; gap: 6px;
}
.progress .stage-chip.active { background: var(--accent-faint); border-color: var(--accent-line); color: var(--accent); }
.progress .stage-chip.done { color: var(--ink-muted); }
.progress .live-transcript { font-family: var(--serif); font-size: 17px; line-height: 1.7; color: var(--ink); }
.progress .live-transcript .turn { display: grid; grid-template-columns: 70px 110px 1fr; gap: 18px; padding: 10px 0; align-items: baseline; }
.progress .live-transcript .ts { font-family: var(--mono); font-size: 11px; color: var(--ink-dim); text-align: right; padding-top: 4px; }
.progress .live-transcript .spk { font-family: var(--serif); font-style: italic; font-size: 14px; color: var(--ink-muted); }
```

- [ ] **Step 2: Component**

`ui/src/screens/ProgressScreen.tsx`:

```tsx
import { useJobs } from '../stores/jobs';

const STAGES = ['ingest', 'asr', 'diarize', 'merge', 'write'] as const;

function fmtTimestamp(secs: number) {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

export function ProgressScreen({ jobId, audioPath }: { jobId: string; audioPath: string }) {
  const job = useJobs(s => s.byId[jobId]);
  if (!job) return null;
  const currentIdx = STAGES.indexOf(job.stage as typeof STAGES[number]);
  const overallPercent = ((currentIdx + job.percent) / STAGES.length) * 100;

  return (
    <div className="progress">
      <div className="doc-head">
        <div className="file-meta">{audioPath}</div>
        <h1>Transcribing…</h1>
      </div>
      <div className="bar"><div style={{ width: `${overallPercent}%` }} /></div>
      <div className="stages">
        {STAGES.map((s, i) => {
          const cls = i < currentIdx ? 'done' : i === currentIdx ? 'active' : '';
          return <span key={s} className={'stage-chip ' + cls}>{s}{i === currentIdx ? ` ${Math.round(job.percent * 100)}%` : ''}</span>;
        })}
      </div>
      <div className="live-transcript">
        {job.lines.map((l, i) => (
          <div key={i} className="turn">
            <div className="ts">{fmtTimestamp(l.ts)}</div>
            <div className="spk">{l.speaker}</div>
            <p>{l.text}</p>
          </div>
        ))}
      </div>
      {job.status === 'failed' && <div style={{ color: 'var(--danger)' }}>{job.error}</div>}
    </div>
  );
}
```

- [ ] **Step 3: Wire into App.tsx**

```tsx
{route === 'progress' && currentJobId && (
  <ProgressScreen jobId={currentJobId} audioPath={/* lookup */ ''} />
)}
```

Subscribe to job status: when `job.status === 'complete'` and `job.paths.json` is set, derive `transcript_id` from the filename and `setRoute('complete')`. Use a small `useEffect` in App.

- [ ] **Step 4: Commit**

```bash
git add ui/
git commit -m "feat(ui): in-progress screen (progress bar, stage chips, live transcript)"
```

---

# Milestone 7 — Complete screen

### Task 25: Complete screen — high-fi

Port [screens.jsx#L222–301](../../design_handoff_locallexis/screens.jsx) `CompleteScreen` to TSX. Wire relabel to `/transcripts/{id}/relabel`.

**Files:**
- Create: `ui/src/screens/CompleteScreen.tsx`
- Create: `ui/src/screens/CompleteScreen.test.tsx`
- Modify: `ui/src/styles/global.css` (port `.complete`, `.doc-head`, `.relabel`, `.transcript` and child rules from handoff)
- Modify: `ui/src/App.tsx`

- [ ] **Step 1: Port styles**

Append to `ui/src/styles/global.css` lines ~648–823 of handoff styles.css (COMPLETE section).

- [ ] **Step 2: Test**

`ui/src/screens/CompleteScreen.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { CompleteScreen } from './CompleteScreen';
import type { TranscriptDoc } from '../api/types';

const doc: TranscriptDoc = {
  version: 1,
  audio_path: '/Audio/meet.mp3',
  duration_seconds: 60,
  language: 'en',
  speakers: { SPEAKER_00: 'Alice', SPEAKER_01: 'Bob' },
  segments: [
    { start: 0, end: 5, speaker: 'SPEAKER_00', text: 'hi' },
    { start: 5, end: 10, speaker: 'SPEAKER_01', text: 'hey' },
  ],
  models: { asr: 'faster-whisper:large-v3' },
  created_at: '2026-05-15T10:00:00Z',
};

test('renders all segments with speaker labels', () => {
  render(<CompleteScreen doc={doc} onRelabel={() => {}} />);
  expect(screen.getByText('Alice')).toBeInTheDocument();
  expect(screen.getByText('Bob')).toBeInTheDocument();
  expect(screen.getByText('hi')).toBeInTheDocument();
});

test('editing a relabel input enables Apply', () => {
  const onRelabel = vi.fn();
  render(<CompleteScreen doc={doc} onRelabel={onRelabel} />);
  const inputs = screen.getAllByDisplayValue(/Alice|Bob/);
  fireEvent.change(inputs[0], { target: { value: 'Carol' } });
  fireEvent.click(screen.getByText('Apply'));
  expect(onRelabel).toHaveBeenCalledWith({ SPEAKER_00: 'Carol' });
});
```

- [ ] **Step 3: Implement**

`ui/src/screens/CompleteScreen.tsx`: port the handoff structure with these adaptations:
- Props: `{ doc: TranscriptDoc; onRelabel: (mapping: Record<string, string>) => void }`.
- Replace `SAMPLE_TURNS` with `doc.segments`.
- Use `SPEAKER_COLORS` from `primitives/colors`.
- The relabel form starts with `Object.entries(doc.speakers)`.
- Compute "Done in N:MM" from `created_at` later (skip for now, omit chip).
- Copy/Open .txt/Open .json buttons: wire Copy to navigator.clipboard.writeText(rendered text); open buttons call Tauri's `shell.open(path)` (add `@tauri-apps/plugin-shell`).
- Both "margin" and "inline" transcript views aren't togglable in v1 — only the margin view ships.

- [ ] **Step 4: Wire**

```tsx
{route === 'complete' && tid && (
  <CompleteScreen
    doc={useTranscripts(s => s.byId[tid])}
    onRelabel={(m) => useTranscripts.getState().relabel(tid, m)}
  />
)}
```

- [ ] **Step 5: Commit**

```bash
cd ui && pnpm test --run
git add ui/
git commit -m "feat(ui): Complete screen (high-fi) — relabel + manuscript transcript"
```

---

# Milestone 8 — Record screen

### Task 26: Record screen — high-fi

Port [screens.jsx#L82–220](../../design_handoff_locallexis/screens.jsx) `RecordScreen` (including `Waveform` SVG).

**Files:**
- Create: `ui/src/screens/RecordScreen.tsx`
- Create: `ui/src/screens/Waveform.tsx`
- Create: `ui/src/screens/RecordScreen.test.tsx`
- Modify: `ui/src/styles/global.css` (port `.record`, `.device-bar`, `.lexis-canvas`, `.timer`, `.record-controls`, `.btn-record`, `.btn-secondary`, `.privacy-note`)
- Modify: `ui/src/App.tsx`

- [ ] **Step 1: Port styles**

Append handoff styles.css lines ~499–646 (RECORD section).

- [ ] **Step 2: Waveform**

Copy the `Waveform` function from handoff `screens.jsx` lines 82–148 into `ui/src/screens/Waveform.tsx`, adapt to TSX (typed prop `{ recording: boolean }`).

- [ ] **Step 3: Test**

`ui/src/screens/RecordScreen.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { RecordScreen } from './RecordScreen';

test('record button toggles recording state', () => {
  const start = vi.fn(); const stop = vi.fn();
  render(<RecordScreen devices={[]} onStart={start} onStop={stop} active={false} elapsed={0} />);
  fireEvent.click(screen.getByTitle('Start recording'));
  expect(start).toHaveBeenCalled();
});

test('timer renders mm:ss with tabular nums', () => {
  render(<RecordScreen devices={[]} onStart={() => {}} onStop={() => {}} active={true} elapsed={73.4} />);
  expect(screen.getByText('01:13')).toBeInTheDocument();
});
```

- [ ] **Step 4: Implement**

`ui/src/screens/RecordScreen.tsx`: port handoff structure, props:

```ts
interface Props {
  devices: AudioDeviceDto[];
  active: boolean;
  paused?: boolean;
  elapsed: number;
  onStart: (device: string | null) => void;
  onStop: () => void;
  onPause?: () => void;
  onDiscard?: () => void;
  outputPath: string;
}
```

Pull device list from `/devices` in App and pass in. Output path defaults to `~/Recordings/voice-memo-NN.wav` — generate next index in the App layer.

- [ ] **Step 5: Wire**

In App, on `route === 'record'`:
- On mount, fetch `/devices` via `api<AudioDeviceDto[]>('/devices')` inside a `useEffect` and hold them in a `useState<AudioDeviceDto[]>([])`.
- `onStart`: `startRecord(outPath, device)` → store jobId in `useRecording`, set `active=true`. Start a `setInterval(() => useRecording.getState().tick(0.1), 100)` and clear it on stop.
- `onStop`: `stopRecord(jobId)` → set `active=false`. Then automatically call `startTranscribe(outPath)` and `setRoute('progress')`.

- [ ] **Step 6: Commit**

```bash
cd ui && pnpm test --run
cd ui && pnpm tauri dev
# manual smoke: record 5 seconds, stop, observe transition to progress + complete
git add ui/
git commit -m "feat(ui): Record screen (high-fi) — device pill, waveform, timer, controls"
```

---

# Milestone 9 — Library / Watch / Settings

### Task 27: Design note — Library screen

**Files:**
- Create: `docs/design_handoff_locallexis/library-screen.md`

- [ ] **Step 1: Write design note**

Cover: layout (search bar + filterable list), row structure (`audio name · duration · speaker count · date · model chip · open arrow`), empty state, error state, sort order (most-recent-first), interaction (click → load + setRoute('complete')). ASCII wireframe. ~250 words.

- [ ] **Step 2: Commit**

```bash
git add docs/design_handoff_locallexis/library-screen.md
git commit -m "design: Library screen layout note"
```

---

### Task 28: Library screen — implementation

**Files:**
- Create: `ui/src/screens/LibraryScreen.tsx`
- Modify: `ui/src/styles/global.css` (`.library`, `.lib-search`, `.lib-row`)
- Modify: `ui/src/App.tsx`

- [ ] **Step 1: Styles**

Append minimal block matching the design note (search input, row grid). Use existing tokens.

- [ ] **Step 2: Component**

```tsx
import { useEffect, useMemo, useState } from 'react';
import { Icon } from '../primitives/Icon';
import { useLibrary } from '../stores/library';
import { useTranscripts } from '../stores/transcripts';
import type { Route } from '../types/route';

export function LibraryScreen({ setRoute, setTid }: { setRoute: (r: Route) => void; setTid: (id: string) => void }) {
  const items = useLibrary(s => s.items);
  const refresh = useLibrary(s => s.refresh);
  const load = useTranscripts(s => s.load);
  const [q, setQ] = useState('');

  useEffect(() => { refresh(); }, [refresh]);

  const filtered = useMemo(() => {
    const needle = q.toLowerCase();
    return items.filter(i => (i.audio_path || i.id).toLowerCase().includes(needle));
  }, [items, q]);

  return (
    <div className="library">
      <div className="lib-search">
        <Icon name="search" size={14} />
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search transcripts…" />
      </div>
      {filtered.length === 0 && <div className="lib-empty">No transcripts yet.</div>}
      <div className="lib-list">
        {filtered.map(i => (
          <div key={i.id} className="lib-row" onClick={async () => { await load(i.id); setTid(i.id); setRoute('complete'); }}>
            <span className="name">{(i.audio_path || i.id).split('/').pop()}</span>
            <span className="meta">{i.duration_seconds ? fmt(i.duration_seconds) : '—'} · {i.speakers ?? '?'} speakers · {i.language ?? '—'}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function fmt(s: number) { return `${Math.floor(s/60)}:${(Math.floor(s%60)).toString().padStart(2,'0')}`; }
```

- [ ] **Step 3: Wire in App**

```tsx
{route === 'library' && <LibraryScreen setRoute={setRoute} setTid={setTid} />}
```

- [ ] **Step 4: Commit**

```bash
git add ui/
git commit -m "feat(ui): Library screen (search + transcript list)"
```

---

### Task 29: Design note — Watch folder screen

**Files:**
- Create: `docs/design_handoff_locallexis/watch-screen.md`

- [ ] **Step 1: Write note**

Cover: folder picker (button → Tauri dialog), running/stopped state with toggle, recent-events log (newest at top, `kind: queued | done | error`), recursive toggle. ASCII wireframe. ~200 words.

- [ ] **Step 2: Commit**

```bash
git add docs/design_handoff_locallexis/watch-screen.md
git commit -m "design: Watch folder screen layout note"
```

---

### Task 30: Watch screen — implementation

**Files:**
- Create: `ui/src/screens/WatchScreen.tsx`
- Modify: `ui/src/styles/global.css`
- Modify: `ui/src/App.tsx`

- [ ] **Step 1: Component**

```tsx
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { open } from '@tauri-apps/plugin-dialog';

interface Status { running: boolean; directory: string | null; events: { ts: number; kind: string; path?: string; message?: string }[] }

export function WatchScreen() {
  const [status, setStatus] = useState<Status | null>(null);
  const [recursive, setRecursive] = useState(false);

  const refresh = async () => setStatus(await api<Status>('/watch/status'));
  useEffect(() => { refresh(); const id = setInterval(refresh, 1000); return () => clearInterval(id); }, []);

  const pick = async () => {
    const dir = await open({ directory: true, multiple: false });
    if (typeof dir !== 'string') return;
    await api('/watch/start', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ directory: dir, recursive }) });
    await refresh();
  };
  const stop = async () => { await api('/watch/stop', { method: 'POST' }); await refresh(); };

  return (
    <div className="watch">
      <div className="watch-control">
        {status?.running ? (
          <>
            <div className="watch-active">Watching <code>{status.directory}</code></div>
            <button onClick={stop}>Stop</button>
          </>
        ) : (
          <>
            <button onClick={pick}>Choose folder…</button>
            <label><input type="checkbox" checked={recursive} onChange={e => setRecursive(e.target.checked)} /> Recursive</label>
          </>
        )}
      </div>
      <div className="watch-events">
        {(status?.events || []).map((e, i) => (
          <div key={i} className={'evt evt-' + e.kind}>
            <span className="ts">{new Date(e.ts * 1000).toLocaleTimeString()}</span>
            <span className="msg">{e.path || e.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

Styles: minimal, reusing tokens — `.watch`, `.watch-control`, `.watch-active`, `.watch-events`, `.evt`.

- [ ] **Step 2: Wire + commit**

```tsx
{route === 'watch' && <WatchScreen />}
```

```bash
git add ui/
git commit -m "feat(ui): Watch folder screen (picker + status + event log)"
```

---

### Task 31: Design note — Settings screen

**Files:**
- Create: `docs/design_handoff_locallexis/settings-screen.md`

- [ ] **Step 1: Write note**

Cover: form fields (backend select, asr_model input, hf_token masked input, model_cache_dir folder picker, default_out_dir folder picker, watch.recursive toggle, watch.debounce_seconds number, watch.extensions text input). Save behavior (per-field on blur, or single Save button — recommend single Save with dirty-state indicator). `hf_token_set: false` triggers a top banner. ~250 words.

- [ ] **Step 2: Commit**

```bash
git add docs/design_handoff_locallexis/settings-screen.md
git commit -m "design: Settings screen layout note"
```

---

### Task 32: Settings screen — implementation

**Files:**
- Create: `ui/src/screens/SettingsScreen.tsx`
- Modify: `ui/src/styles/global.css`
- Modify: `ui/src/App.tsx`

- [ ] **Step 1: Component**

```tsx
import { useEffect, useState } from 'react';
import { useConfig } from '../stores/config';
import type { ConfigDto } from '../api/types';

export function SettingsScreen() {
  const cfg = useConfig(s => s.cfg);
  const load = useConfig(s => s.load);
  const patch = useConfig(s => s.patch);
  const [draft, setDraft] = useState<Partial<ConfigDto> & { hf_token?: string }>({});
  const [dirty, setDirty] = useState(false);

  useEffect(() => { load(); }, [load]);
  if (!cfg) return null;

  const update = <K extends keyof ConfigDto>(k: K, v: ConfigDto[K]) => {
    setDraft(d => ({ ...d, [k]: v })); setDirty(true);
  };

  return (
    <div className="settings">
      {!cfg.hf_token_set && !draft.hf_token && (
        <div className="banner warn">Hugging Face token not set — diarization will fail without it.</div>
      )}
      <Field label="Backend">
        <select defaultValue={cfg.backend} onChange={e => update('backend', e.target.value as ConfigDto['backend'])}>
          {['auto','cpu','cuda','mps'].map(b => <option key={b} value={b}>{b}</option>)}
        </select>
      </Field>
      <Field label="ASR model">
        <input defaultValue={cfg.asr_model} onChange={e => update('asr_model', e.target.value)} />
      </Field>
      <Field label="Hugging Face token">
        <input type="password" placeholder={cfg.hf_token_set ? '••••••••' : 'hf_…'} onChange={e => { setDraft(d => ({ ...d, hf_token: e.target.value })); setDirty(true); }} />
      </Field>
      <Field label="Model cache dir">
        <input defaultValue={cfg.model_cache_dir} onChange={e => update('model_cache_dir', e.target.value)} />
      </Field>
      <Field label="Watch debounce (s)">
        <input type="number" defaultValue={cfg.watch.debounce_seconds} onChange={e => update('watch' as any, { ...cfg.watch, debounce_seconds: Number(e.target.value) })} />
      </Field>
      <button disabled={!dirty} onClick={async () => { await patch(draft); setDraft({}); setDirty(false); }}>
        {dirty ? 'Save' : 'Saved'}
      </button>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="field"><span>{label}</span>{children}</label>;
}
```

Styles minimal; reuse tokens.

- [ ] **Step 2: Wire + commit**

```bash
git add ui/
git commit -m "feat(ui): Settings screen (form editor for config.toml)"
```

---

# Milestone 10 — Ship

### Task 33: Tauri smoke test — sidecar lifecycle

**Files:**
- Create: `ui/src-tauri/tests/integration.rs`

- [ ] **Step 1: Skeleton test**

```rust
// Verifies the sidecar starts, reports a port, and responds to /health.
// Run with: cargo test --manifest-path ui/src-tauri/Cargo.toml -- --test-threads=1
```

Implementation: build the binary in `ui/src-tauri/binaries/`, spawn it directly (without Tauri), parse the JSON handshake from stdout within 10s, GET `/health`, assert `{ok: true}`, then kill the child. ~60 lines of Rust.

- [ ] **Step 2: Commit**

```bash
git add ui/src-tauri/tests
git commit -m "test(ui): sidecar lifecycle smoke test"
```

---

### Task 34: Full-app CI — Tauri builds for Mac/Windows/Linux

**Files:**
- Create: `.github/workflows/build-app.yml`

- [ ] **Step 1: Workflow**

```yaml
name: build-app
on:
  push: { branches: [main] }
  pull_request:
jobs:
  build:
    strategy: { fail-fast: false, matrix: { os: [ubuntu-latest, macos-14, windows-latest] } }
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - uses: dtolnay/rust-toolchain@stable
      - uses: pnpm/action-setup@v3
        with: { version: 9 }
      - uses: actions/setup-node@v4
        with: { node-version: 20, cache: 'pnpm', cache-dependency-path: ui/pnpm-lock.yaml }
      - name: System deps (Linux)
        if: runner.os == 'Linux'
        run: |
          sudo apt-get update
          sudo apt-get install -y libwebkit2gtk-4.1-dev libsoup-3.0-dev ffmpeg
      - name: Build sidecar
        run: |
          pip install -e ".[api,packaging]"
          pyinstaller packaging/locallexis-sidecar.spec --clean
          mkdir -p ui/src-tauri/binaries
          cp dist/locallexis-sidecar* ui/src-tauri/binaries/
      - name: Install JS deps
        working-directory: ui
        run: pnpm install
      - name: Build Tauri app
        working-directory: ui
        run: pnpm tauri build
      - uses: actions/upload-artifact@v4
        with:
          name: locallexis-${{ runner.os }}
          path: |
            ui/src-tauri/target/release/bundle/**/*
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/build-app.yml
git commit -m "ci: build LocalLexis app for Mac/Windows/Linux"
```

---

### Task 35: README updates

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a Desktop section**

Append after the CLI section:

```markdown
## Desktop app — LocalLexis

A cross-platform desktop UI lives in `ui/`. It wraps the CLI through a
bundled FastAPI sidecar, with full feature parity plus a transcript
library.

Local dev:

    # 1. Build the sidecar
    pip install -e ".[api,packaging]"
    pyinstaller packaging/locallexis-sidecar.spec --clean
    mkdir -p ui/src-tauri/binaries
    cp dist/locallexis-sidecar* ui/src-tauri/binaries/

    # 2. Run the app in dev mode
    cd ui && pnpm install && pnpm tauri dev

Release builds are produced by `.github/workflows/build-app.yml` for
macOS, Windows, and Linux.

Design references live in `docs/design_handoff_locallexis/`. Run
`open docs/design_handoff_locallexis/LocalLexis-standalone.html` to
see the high-fi prototype.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README — desktop app build instructions"
```

---

## Spec Coverage Check

| Spec section                     | Tasks covering it           |
| -------------------------------- | --------------------------- |
| Three-layer architecture         | 2–11, 14–18                 |
| FastAPI endpoint contract        | 2–11                        |
| SSE event shape                  | 5, 6, 17                    |
| Tauri shell + sidecar lifecycle  | 14, 16, 33, 34              |
| Dark manuscript theme + fonts    | 15                          |
| Sidebar (handoff)                | 20                          |
| Main header (handoff)            | 21                          |
| Idle screen (high-fi)            | 22                          |
| In-progress (design + build)     | 23, 24                      |
| Complete screen (high-fi)        | 25                          |
| Record screen (high-fi)          | 26                          |
| Library (design + build)         | 27, 28                      |
| Watch folder (design + build)    | 29, 30                      |
| Settings (design + build)        | 31, 32                      |
| Frontend state shape             | 18                          |
| Error handling (SSE error event) | 2, 5, 18, 24                |
| Library = scan `.json` sidecars  | 8                           |
| Testing layers                   | 2–11 (API), 19–32 (UI), 33  |
| Cross-platform CI                | 13, 34                      |
| Phase 2 reserved endpoints       | None — explicitly deferred  |

No spec sections without coverage.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-15-locallexis-desktop-ui.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
