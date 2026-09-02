from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


def _write(tmp_path: Path, tid="rec", with_txt=True):
    doc = {
        "audio_path": str(tmp_path / f"{tid}.wav"),
        "duration_seconds": 1.0,
        "language": "en",
        "speakers": {},
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "S1", "text": "hoi"}],
        "models": {},
        "created_at": "2026-07-07T10:00:00+00:00",
    }
    json_path = tmp_path / f"{tid}.json"
    json_path.write_text(json.dumps(doc), encoding="utf-8")
    if with_txt:
        (tmp_path / f"{tid}.txt").write_text("S1: hoi\n", encoding="utf-8")
    return json_path


def _make_client(tmp_path: Path) -> TestClient:
    app = create_app(library_db_path=tmp_path / "library.db")
    app.state.library_dirs.add(tmp_path)
    return TestClient(app)


def test_download_json(tmp_path):
    client = _make_client(tmp_path)
    json_path = _write(tmp_path)
    r = client.get("/transcripts/rec/file/json")
    assert r.status_code == 200
    assert r.content == json_path.read_bytes()
    assert r.headers["content-type"].startswith("application/json")
    cd = r.headers["content-disposition"]
    assert "attachment" in cd and "rec.json" in cd


def test_download_txt(tmp_path):
    client = _make_client(tmp_path)
    _write(tmp_path)
    r = client.get("/transcripts/rec/file/txt")
    assert r.status_code == 200
    assert r.text == "S1: hoi\n"
    assert r.headers["content-type"].startswith("text/plain")
    assert "rec.txt" in r.headers["content-disposition"]


def test_download_txt_missing_404(tmp_path):
    client = _make_client(tmp_path)
    _write(tmp_path, with_txt=False)
    assert client.get("/transcripts/rec/file/txt").status_code == 404


def test_download_unknown_format_404(tmp_path):
    client = _make_client(tmp_path)
    _write(tmp_path)
    assert client.get("/transcripts/rec/file/pdf").status_code == 404


def test_download_unknown_tid_404(tmp_path):
    client = _make_client(tmp_path)
    assert client.get("/transcripts/nope/file/json").status_code == 404
