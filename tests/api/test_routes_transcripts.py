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
