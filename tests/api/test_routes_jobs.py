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


from unittest.mock import patch


def test_post_record_creates_job(tmp_path, monkeypatch):
    from speechtotext.api.app import create_app
    app = create_app()
    out = tmp_path / "rec.wav"
    client = TestClient(app)

    with patch("speechtotext.api.runner.record_to_wav") as rec:
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
