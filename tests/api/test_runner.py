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
