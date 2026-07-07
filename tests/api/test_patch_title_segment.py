from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app
from tests.api.test_routes_transcripts import _pair_device, _signed_patch


def _write_transcript(dir: Path, tid: str = "meeting") -> Path:
    doc = {
        "version": 2,
        "audio_path": str(dir / f"{tid}.wav"),
        "duration_seconds": 2.0,
        "language": "en",
        "speakers": {"SPEAKER_00": "Alice"},
        "segments": [
            {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": "hello"},
            {"start": 1.0, "end": 2.0, "speaker": "SPEAKER_00", "text": "world"},
        ],
        "models": {"asr": "faster-whisper:base.en"},
        "created_at": "2026-07-07T10:00:00+00:00",
        "_workspace_id": "ws-test",
        "_clocks": {},
        "_history": [],
    }
    p = dir / f"{tid}.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    (dir / f"{tid}.txt").write_text("[00:00:00] Alice: hello\n[00:00:01] Alice: world\n")
    return p


@pytest.fixture
def library_dir(tmp_path) -> Path:
    return tmp_path


@pytest.fixture
def app_with_lib(tmp_path):
    app = create_app(library_db_path=tmp_path / "library.db")
    app.state.library_dirs.add(tmp_path)
    return app


@pytest.fixture
def client(app_with_lib):
    return TestClient(app_with_lib)


def _patch_op(client, library_dir, op, key, value, tid="meeting"):
    sk, dev_id = _pair_device(client)
    return _signed_patch(
        client, sk, dev_id, f"/transcripts/{tid}",
        {"op": op, "key": key, "value": value, "lamport_observed": 0},
    )


def test_set_title_persists(client, library_dir):
    p = _write_transcript(library_dir)
    r = _patch_op(client, library_dir, "set_title", "title", "Weekly sync")
    assert r.status_code == 200, r.text
    doc = json.loads(p.read_text())
    assert doc["title"] == "Weekly sync"


def test_set_title_surfaces_in_library_listing(client, library_dir):
    _write_transcript(library_dir)
    r = _patch_op(client, library_dir, "set_title", "title", "Weekly sync")
    assert r.status_code == 200, r.text
    items = client.get("/transcripts").json()
    assert any(i.get("title") == "Weekly sync" for i in items)


def test_edit_segment_rewrites_json_and_txt(client, library_dir):
    p = _write_transcript(library_dir)
    r = _patch_op(client, library_dir, "edit_segment", "segments.1.text", "world, edited")
    assert r.status_code == 200, r.text
    doc = json.loads(p.read_text())
    assert doc["segments"][1]["text"] == "world, edited"
    txt = (library_dir / "meeting.txt").read_text()
    assert "world, edited" in txt
    assert "Alice" in txt  # speaker display names survive the rewrite


def test_edit_segment_out_of_range_400(client, library_dir):
    _write_transcript(library_dir)
    r = _patch_op(client, library_dir, "edit_segment", "segments.99.text", "x")
    assert r.status_code == 400


def test_edited_segment_text_searchable(client, library_dir):
    _write_transcript(library_dir)
    r = _patch_op(
        client, library_dir, "edit_segment", "segments.0.text", "xylophone rehearsal"
    )
    assert r.status_code == 200, r.text
    items = client.get("/transcripts", params={"q": "xylophone"}).json()
    assert len(items) == 1
