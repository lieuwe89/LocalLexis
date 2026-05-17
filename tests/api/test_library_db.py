"""Tests for the SQLite + FTS5 library index."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from speechtotext.api.library_db import LibraryDB, _quote_fts


def _make_doc(text_segments: list[tuple[float, float, str, str]],
              audio_name: str = "meeting.mp3",
              language: str = "en",
              speakers: dict[str, str] | None = None) -> dict:
    return {
        "version": 1,
        "audio_path": f"/some/dir/{audio_name}",
        "duration_seconds": text_segments[-1][1] if text_segments else 0.0,
        "language": language,
        "speakers": speakers or {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"},
        "segments": [
            {"start": s, "end": e, "speaker": sp, "text": t}
            for s, e, sp, t in text_segments
        ],
        "models": {"asr": "faster-whisper:base.en", "diarizer": "pyannote:3.1",
                   "backend": "cpu"},
        "created_at": "2026-05-17T12:00:00+00:00",
    }


def _write(dir: Path, name: str, doc: dict) -> Path:
    p = dir / f"{name}.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


@pytest.fixture
def db(tmp_path: Path) -> LibraryDB:
    return LibraryDB(tmp_path / "library.db")


def test_quote_fts_escapes_and_appends_prefix():
    assert _quote_fts("hello world") == '"hello"* "world"*'
    assert _quote_fts('  foo  bar  ') == '"foo"* "bar"*'
    assert _quote_fts('say "hi"') == '"say"* """hi"""*'
    assert _quote_fts("") == ""
    assert _quote_fts("   ") == ""


def test_upsert_and_list(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "alpha", _make_doc([(0.0, 1.0, "SPEAKER_00", "hello world")]))
    db.upsert_path(p)
    rows = db.list()
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == "alpha"
    assert r["path"] == str(p)
    assert r["audio_path"] == "/some/dir/meeting.mp3"
    assert r["language"] == "en"
    assert r["speakers"] == 2
    assert r["models"]["asr"] == "faster-whisper:base.en"


def test_upsert_is_idempotent(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "a", _make_doc([(0.0, 1.0, "SPEAKER_00", "hello")]))
    db.upsert_path(p)
    db.upsert_path(p)
    rows = db.list()
    assert len(rows) == 1


def test_search_finds_content(db: LibraryDB, tmp_path: Path):
    _write(tmp_path, "a", _make_doc(
        [(0.0, 2.0, "SPEAKER_00", "discussion of climate change adaptation policy")]
    ))
    _write(tmp_path, "b", _make_doc(
        [(0.0, 2.0, "SPEAKER_00", "lunch order for the team meeting")]
    ))
    db.sync_dirs([tmp_path])
    hits = db.search("climate")
    assert len(hits) == 1
    assert hits[0]["id"] == "a"
    assert "snippet" in hits[0]
    assert "<mark>" in hits[0]["snippet"]


def test_search_finds_filename(db: LibraryDB, tmp_path: Path):
    _write(tmp_path, "a", _make_doc(
        [(0.0, 1.0, "SPEAKER_00", "yes")], audio_name="standup-2026-05-17.wav",
    ))
    _write(tmp_path, "b", _make_doc(
        [(0.0, 1.0, "SPEAKER_00", "no")], audio_name="lunch-2026-05-18.wav",
    ))
    db.sync_dirs([tmp_path])
    hits = db.search("standup")
    assert len(hits) == 1
    assert hits[0]["id"] == "a"


def test_search_finds_speaker_label(db: LibraryDB, tmp_path: Path):
    _write(tmp_path, "a", _make_doc(
        [(0.0, 1.0, "SPEAKER_00", "text")], speakers={"SPEAKER_00": "Marie Curie"},
    ))
    _write(tmp_path, "b", _make_doc(
        [(0.0, 1.0, "SPEAKER_00", "text")], speakers={"SPEAKER_00": "Albert Einstein"},
    ))
    db.sync_dirs([tmp_path])
    hits = db.search("Marie")
    assert len(hits) == 1
    assert hits[0]["id"] == "a"


def test_search_ranks_relevance(db: LibraryDB, tmp_path: Path):
    # "budget" appears once in a, many times in b — b should rank higher
    _write(tmp_path, "a", _make_doc(
        [(0.0, 1.0, "SPEAKER_00", "we briefly mentioned the budget")],
    ))
    _write(tmp_path, "b", _make_doc(
        [(0.0, 1.0, "SPEAKER_00",
          "budget budget budget — finalising the budget for next quarter")],
    ))
    db.sync_dirs([tmp_path])
    hits = db.search("budget")
    assert [h["id"] for h in hits] == ["b", "a"]


def test_sync_dirs_skips_unchanged(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "a", _make_doc([(0.0, 1.0, "SPEAKER_00", "hi")]))
    s1 = db.sync_dirs([tmp_path])
    assert s1["upserted"] == 1
    s2 = db.sync_dirs([tmp_path])
    assert s2["upserted"] == 0  # unchanged mtime+size, skipped
    # touch the file -> changed mtime triggers re-upsert
    later = time.time() + 5
    import os
    os.utime(p, (later, later))
    s3 = db.sync_dirs([tmp_path])
    assert s3["upserted"] == 1


def test_sync_dirs_removes_deleted_files(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "a", _make_doc([(0.0, 1.0, "SPEAKER_00", "hi")]))
    db.sync_dirs([tmp_path])
    p.unlink()
    s = db.sync_dirs([tmp_path])
    assert s["deleted"] == 1
    assert db.list() == []


def test_get_path_round_trips(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "a", _make_doc([(0.0, 1.0, "SPEAKER_00", "hi")]))
    db.upsert_path(p)
    assert db.get_path("a") == p
    assert db.get_path("nope") is None


def test_relabel_updates_speaker_search(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "a", _make_doc(
        [(0.0, 1.0, "SPEAKER_00", "hi")], speakers={"SPEAKER_00": "Alice"},
    ))
    db.upsert_path(p)
    assert len(db.search("Alice")) == 1
    # Simulate relabel by rewriting the JSON and re-upserting.
    doc = json.loads(p.read_text())
    doc["speakers"]["SPEAKER_00"] = "Beatrice"
    p.write_text(json.dumps(doc))
    db.upsert_path(p)
    assert db.search("Alice") == []
    assert len(db.search("Beatrice")) == 1


def test_chunks_and_embeddings_tables_present(db: LibraryDB):
    # Forward-compat: schema must include the RAG stubs even though they
    # are unused today.
    with db._lock:
        names = {
            row[0]
            for row in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "chunks" in names
    assert "embeddings" in names


def test_corrupt_json_is_recorded_as_error(db: LibraryDB, tmp_path: Path):
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    db.upsert_path(bad)
    rows = db.list()
    assert len(rows) == 1
    assert rows[0]["error"] == "parse"
