from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


def _write(tmp_path: Path, tid="rec", audio_bytes=b"RIFF" + bytes(100)):
    audio = tmp_path / f"{tid}.wav"
    audio.write_bytes(audio_bytes)
    doc = {
        "audio_path": str(audio), "duration_seconds": 1.0, "language": "en",
        "speakers": {}, "segments": [], "models": {},
        "created_at": "2026-07-07T10:00:00+00:00",
    }
    (tmp_path / f"{tid}.json").write_text(json.dumps(doc), encoding="utf-8")
    return audio


def _make_client(tmp_path: Path) -> TestClient:
    app = create_app(library_db_path=tmp_path / "library.db")
    app.state.library_dirs.add(tmp_path)
    return TestClient(app)


def test_full_audio(tmp_path):
    client = _make_client(tmp_path)
    audio = _write(tmp_path)
    r = client.get("/transcripts/rec/audio")
    assert r.status_code == 200
    assert r.content == audio.read_bytes()
    assert r.headers["accept-ranges"] == "bytes"
    assert r.headers["content-type"].startswith("audio/")


def test_range_request(tmp_path):
    client = _make_client(tmp_path)
    _write(tmp_path)
    r = client.get("/transcripts/rec/audio", headers={"Range": "bytes=4-9"})
    assert r.status_code == 206
    assert r.content == bytes(6)  # bytes 4..9 of RIFF+zeros
    assert r.headers["content-range"] == "bytes 4-9/104"


def test_open_ended_range(tmp_path):
    client = _make_client(tmp_path)
    _write(tmp_path)
    r = client.get("/transcripts/rec/audio", headers={"Range": "bytes=100-"})
    assert r.status_code == 206
    assert len(r.content) == 4


def test_audio_file_missing_404(tmp_path):
    client = _make_client(tmp_path)
    audio = _write(tmp_path)
    audio.unlink()
    assert client.get("/transcripts/rec/audio").status_code == 404


def test_unknown_transcript_404(tmp_path):
    client = _make_client(tmp_path)
    assert client.get("/transcripts/nope/audio").status_code == 404


def test_suffix_range(tmp_path):
    client = _make_client(tmp_path)
    _write(tmp_path)
    r = client.get("/transcripts/rec/audio", headers={"Range": "bytes=-10"})
    assert r.status_code == 206
    assert len(r.content) == 10
    assert r.headers["content-range"] == "bytes 94-103/104"


def test_malformed_range_416(tmp_path):
    client = _make_client(tmp_path)
    _write(tmp_path)
    r = client.get("/transcripts/rec/audio", headers={"Range": "bytes=abc"})
    assert r.status_code == 416
