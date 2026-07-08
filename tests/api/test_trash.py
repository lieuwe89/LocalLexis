from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from speechtotext.api import trash
from speechtotext.api.app import create_app


def _make(dir: Path, tid="rec", title=None):
    audio = dir / f"{tid}.wav"
    audio.write_bytes(b"AUDIO")
    doc = {
        "audio_path": str(audio), "duration_seconds": 1.0, "language": "en",
        "speakers": {}, "segments": [], "models": {},
        "created_at": "2026-07-07T10:00:00+00:00",
    }
    if title:
        doc["title"] = title
    (dir / f"{tid}.json").write_text(json.dumps(doc), encoding="utf-8")
    (dir / f"{tid}.txt").write_text("txt")
    return dir / f"{tid}.json"


def _client(tmp_path: Path) -> TestClient:
    app = create_app(library_db_path=tmp_path / "library.db")
    app.state.library_dirs.add(tmp_path)
    return TestClient(app)


# --- unit tests on the trash module ---

def test_trash_moves_all_files(tmp_path: Path):
    p = _make(tmp_path, title="My rec")
    trash.trash_transcript(p)
    t = tmp_path / ".trash" / "rec"
    assert (t / "rec.json").is_file()
    assert (t / "rec.txt").is_file()
    assert (t / "rec.wav").is_file()
    assert not p.exists() and not (tmp_path / "rec.wav").exists()
    manifest = json.loads((t / "manifest.json").read_text())
    assert manifest["tid"] == "rec"
    assert manifest["title"] == "My rec"
    assert manifest["files"]["json"] == str(tmp_path / "rec.json")


def test_list_trash(tmp_path: Path):
    trash.trash_transcript(_make(tmp_path, "a"))
    trash.trash_transcript(_make(tmp_path, "b", title="B"))
    items = trash.list_trash([tmp_path])
    assert {i["tid"] for i in items} == {"a", "b"}
    b = next(i for i in items if i["tid"] == "b")
    assert b["title"] == "B" and b["deleted_at"]


def test_restore_round_trip(tmp_path: Path):
    p = _make(tmp_path)
    trash.trash_transcript(p)
    restored = trash.restore([tmp_path], "rec")
    assert p.is_file() and (tmp_path / "rec.wav").is_file()
    assert restored == p
    assert not (tmp_path / ".trash" / "rec").exists()


def test_restore_conflict_raises(tmp_path: Path):
    p = _make(tmp_path)
    trash.trash_transcript(p)
    _make(tmp_path)  # recreate a file at the original path
    with pytest.raises(FileExistsError):
        trash.restore([tmp_path], "rec")
    t = tmp_path / ".trash" / "rec"
    assert t.is_dir()
    assert (t / "rec.json").is_file() and (t / "rec.wav").is_file()


def test_trash_rollback_on_partial_failure(tmp_path, monkeypatch):
    p = _make(tmp_path, "rb")  # json + txt + wav = 3 files to move
    import speechtotext.api.trash as trashmod
    real_replace = Path.replace
    calls = {"n": 0}
    def flaky(self, target):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated failure")
        return real_replace(self, target)
    monkeypatch.setattr(Path, "replace", flaky)
    with pytest.raises(OSError):
        trashmod.trash_transcript(p)
    # rollback: the first-moved file is back at its original location
    # (all originals present, nothing stranded in the trash dir's moved set)
    assert p.exists()  # json restored to original path


def test_purge_one_and_all(tmp_path: Path):
    trash.trash_transcript(_make(tmp_path, "a"))
    trash.trash_transcript(_make(tmp_path, "b"))
    trash.purge([tmp_path], "a")
    assert {i["tid"] for i in trash.list_trash([tmp_path])} == {"b"}
    trash.purge([tmp_path])
    assert trash.list_trash([tmp_path]) == []


# --- route-level tests ---

def test_delete_endpoint_moves_to_trash_and_unlists(tmp_path: Path):
    client = _client(tmp_path)
    _make(tmp_path, "gone")
    client.get("/transcripts")  # prime index
    r = client.delete("/transcripts/gone")
    assert r.status_code == 200
    assert all(i["id"] != "gone" for i in client.get("/transcripts").json())
    trashed = client.get("/trash").json()
    assert trashed[0]["tid"] == "gone"


def test_restore_endpoint(tmp_path: Path):
    client = _client(tmp_path)
    _make(tmp_path, "back")
    client.get("/transcripts")
    client.delete("/transcripts/back")
    r = client.post("/trash/back/restore")
    assert r.status_code == 200
    assert any(i["id"] == "back" for i in client.get("/transcripts").json())
    assert client.get("/trash").json() == []


def test_empty_trash_endpoint(tmp_path: Path):
    client = _client(tmp_path)
    _make(tmp_path, "x")
    client.get("/transcripts")
    client.delete("/transcripts/x")
    assert client.delete("/trash").status_code == 200
    assert client.get("/trash").json() == []
    assert not (tmp_path / ".trash" / "x").exists()


def test_restore_conflict_409(tmp_path: Path):
    client = _client(tmp_path)
    _make(tmp_path, "dup")
    client.get("/transcripts")
    client.delete("/transcripts/dup")
    _make(tmp_path, "dup")
    assert client.post("/trash/dup/restore").status_code == 409


def test_incoming_dir_registered_as_library_dir(tmp_path: Path):
    """Regression: hub uploads are transcribed into incoming_dir, so deletes
    trash them to incoming_dir/.trash. If incoming_dir isn't a library dir,
    a freshly-restarted hub reports an empty /trash even though the files are
    on disk (it's otherwise only added lazily on the next job completion)."""
    app = create_app(library_db_path=tmp_path / "library.db")
    assert app.state.incoming_dir in app.state.library_dirs
