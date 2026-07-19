import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from speechtotext.api.events import CompleteEvent, ErrorEvent, LineEvent, StageEvent
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

        sub = reg.subscribe(job_id)
        run_transcribe_job(reg, job_id, audio)

        events = []
        async for ev in sub:
            events.append(ev)

    types = [type(e).__name__ for e in events]
    assert "StageEvent" in types
    assert "LineEvent" in types
    assert types[-1] == "CompleteEvent"
    assert reg.get(job_id).status == JobStatus.complete


@pytest.mark.asyncio
async def test_cancel_mid_asr_reports_clean_cancel(tmp_path):
    """Regression: a cancel raised inside the ASR loop must end the job as a
    clean 'cancelled', not a generic error.

    faster_whisper.py used to define its own CancelledError, so a job
    cancelled mid-transcription bypassed runner's `except CancelledError`
    (which catches the pipeline's class) and reached the UI as
    'CancelledError: transcription cancelled' instead of 'cancelled'.
    """
    from speechtotext.asr.faster_whisper import CancelledError as ASRCancelledError

    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"fake")
    reg = JobRegistry()
    job_id = reg.create(kind="transcribe", audio_path=str(audio))

    with patch("speechtotext.api.runner._build_pipeline") as build:
        pipe = MagicMock()
        pipe.run.side_effect = ASRCancelledError("transcription cancelled")
        build.return_value = (pipe, "cpu")

        sub = reg.subscribe(job_id)
        run_transcribe_job(reg, job_id, audio)

        events = []
        async for ev in sub:
            events.append(ev)

    last = events[-1]
    assert isinstance(last, ErrorEvent)
    assert last.message == "cancelled"
    rec = reg.get(job_id)
    assert rec.status == JobStatus.failed
    assert rec.error == "cancelled"


@pytest.mark.asyncio
async def test_concurrency_cap_queues_second_job(tmp_path, monkeypatch):
    """With the slot cap at 1, a second job must queue, not load models.

    Two model-loading jobs running at once is the OOM risk. We force the
    first job's pipeline to block while holding the only slot, then assert
    the second job's first emitted event is the ``queued`` stage rather
    than ``load``. Releasing the first frees the slot so the second runs.
    """
    import threading

    import speechtotext.api.runner as runner_mod

    monkeypatch.setattr(
        runner_mod, "_TRANSCRIBE_SEM", threading.BoundedSemaphore(1)
    )
    monkeypatch.setattr(runner_mod, "get_workspace_id", lambda: "ws_test")
    monkeypatch.setattr(
        runner_mod,
        "write_transcript",
        lambda t, workspace_id=None: (
            tmp_path / "x.txt",
            tmp_path / "x.json",
        ),
    )

    a_running = threading.Event()
    release_a = threading.Event()

    def fake_build(cfg, backend):
        pipe = MagicMock()

        def run(audio, **kwargs):
            a_running.set()
            assert release_a.wait(timeout=5)
            return _fake_transcript(audio)

        pipe.run.side_effect = run
        return (pipe, "cpu")

    monkeypatch.setattr(runner_mod, "_build_pipeline", fake_build)

    audio_a = tmp_path / "a.mp3"
    audio_a.write_bytes(b"a")
    audio_b = tmp_path / "b.mp3"
    audio_b.write_bytes(b"b")
    reg = JobRegistry()
    job_a = reg.create(kind="transcribe", audio_path=str(audio_a))
    job_b = reg.create(kind="transcribe", audio_path=str(audio_b))

    sub_b = reg.subscribe(job_b)
    run_transcribe_job(reg, job_a, audio_a)

    # Drive the loop until job A is inside pipeline.run holding the slot.
    for _ in range(100):
        if a_running.is_set():
            break
        await asyncio.sleep(0.02)
    assert a_running.is_set()

    run_transcribe_job(reg, job_b, audio_b)

    first_b = await asyncio.wait_for(sub_b.__anext__(), timeout=5)
    assert isinstance(first_b, StageEvent)
    assert first_b.stage == "queued"

    release_a.set()  # let A finish and release the slot
    events_b = [first_b]
    async for ev in sub_b:
        events_b.append(ev)
    assert type(events_b[-1]).__name__ == "CompleteEvent"
    assert reg.get(job_b).status == JobStatus.complete
