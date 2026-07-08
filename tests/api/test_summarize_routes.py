from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    app = create_app(library_db_path=tmp_path / "library.db")
    app.state.library_dirs.add(tmp_path)
    return TestClient(app)


def _write_transcript(dir: Path, tid="talk"):
    doc = {
        "audio_path": str(dir / f"{tid}.wav"), "duration_seconds": 5.0,
        "language": "en", "speakers": {"S0": "Ann"},
        "segments": [{"start": 0, "end": 5, "speaker": "S0", "text": "we agreed to ship"}],
        "models": {}, "created_at": "2026-07-07T10:00:00+00:00",
    }
    (dir / f"{tid}.json").write_text(json.dumps(doc), encoding="utf-8")


def _wait_job(client, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = client.get(f"/jobs/{job_id}").json()
        if rec["status"] in ("complete", "failed"):
            return rec
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_summarize_writes_summary(tmp_path):
    client = _client(tmp_path)
    _write_transcript(tmp_path)
    client.get("/transcripts")  # prime index
    with patch("speechtotext.api.runner._summarize_provider") as prov:
        prov.return_value.chat.return_value = "## Summary\nShip it."
        prov.return_value.model = "test-model"
        r = client.post("/transcripts/talk/summarize")
        assert r.status_code == 202
        rec = _wait_job(client, r.json()["job_id"])
    assert rec["status"] == "complete"
    assert rec["kind"] == "summarize"
    doc = json.loads((tmp_path / "talk.json").read_text())
    assert doc["summary"] == "## Summary\nShip it."
    assert doc["summary_meta"]["model"]
    assert doc["summary_meta"]["created_at"]


def test_summarize_provider_failure_fails_job(tmp_path):
    client = _client(tmp_path)
    _write_transcript(tmp_path, "bad")
    client.get("/transcripts")
    from speechtotext.summarize.provider import ProviderError
    with patch("speechtotext.api.runner._summarize_provider") as prov:
        prov.return_value.chat.side_effect = ProviderError("cannot reach provider")
        r = client.post("/transcripts/bad/summarize")
        rec = _wait_job(client, r.json()["job_id"])
    assert rec["status"] == "failed"
    assert "cannot reach provider" in rec["error"]


def test_summarize_oversized_transcript_fails_job(tmp_path):
    client = _client(tmp_path)
    doc = {
        "audio_path": str(tmp_path / "huge.wav"), "duration_seconds": 5.0,
        "language": "en", "speakers": {"S0": "Ann"},
        "segments": [{"start": 0, "end": 5, "speaker": "S0", "text": "x" * 600_000}],
        "models": {}, "created_at": "2026-07-07T10:00:00+00:00",
    }
    (tmp_path / "huge.json").write_text(json.dumps(doc), encoding="utf-8")
    client.get("/transcripts")  # prime index
    with patch("speechtotext.api.runner._summarize_provider") as prov:
        r = client.post("/transcripts/huge/summarize")
        assert r.status_code == 202
        rec = _wait_job(client, r.json()["job_id"])
        prov.return_value.chat.assert_not_called()
    assert rec["status"] == "failed"
    assert "too long" in rec["error"]


def test_summarize_unknown_transcript_404(tmp_path):
    client = _client(tmp_path)
    assert client.post("/transcripts/nope/summarize").status_code == 404


def test_summarize_models_proxy(tmp_path):
    client = _client(tmp_path)
    with patch("speechtotext.api.routes_summarize.provider_from_config") as pfc:
        pfc.return_value.list_models.return_value = ["m1", "m2"]
        r = client.get("/summarize/models")
    assert r.status_code == 200
    assert r.json() == {"models": ["m1", "m2"]}


def test_summarize_models_unreachable_502(tmp_path):
    client = _client(tmp_path)
    from speechtotext.summarize.provider import ProviderError
    with patch("speechtotext.api.routes_summarize.provider_from_config") as pfc:
        pfc.return_value.list_models.side_effect = ProviderError("down")
        assert client.get("/summarize/models").status_code == 502
