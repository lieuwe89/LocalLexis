"""Tests for per-segment FTS indexing and schema v2 migration."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from speechtotext.api.library_db import SCHEMA_VERSION, LibraryDB


def _make_doc(text_segments: list[tuple[float, float, str, str]],
              audio_name: str = "meeting.mp3") -> dict:
    return {
        "version": 1,
        "audio_path": f"/some/dir/{audio_name}",
        "duration_seconds": text_segments[-1][1] if text_segments else 0.0,
        "language": "en",
        "speakers": {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"},
        "segments": [
            {"start": s, "end": e, "speaker": sp, "text": t}
            for s, e, sp, t in text_segments
        ],
        "models": {"asr": "faster-whisper:base.en"},
        "created_at": "2026-05-17T12:00:00+00:00",
    }


def _write(dir: Path, name: str, doc: dict) -> Path:
    p = dir / f"{name}.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


@pytest.fixture
def db(tmp_path: Path) -> LibraryDB:
    return LibraryDB(tmp_path / "library.db")


def _seg_rows(db: LibraryDB, table: str, tid: str) -> list[sqlite3.Row]:
    return db._conn.execute(
        f"SELECT * FROM {table} WHERE transcript_id=? ORDER BY segment_index",
        (tid,),
    ).fetchall()


def test_upsert_indexes_each_segment(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "alpha", _make_doc([
        (0.0, 2.0, "SPEAKER_00", "hello world"),
        (2.0, 4.0, "SPEAKER_01", "goodbye moon"),
    ]))
    db.upsert_path(p)
    rows = _seg_rows(db, "segments_fts", "alpha")
    assert [(r["segment_index"], r["text"], r["start"]) for r in rows] == [
        (0, "hello world", 0.0),
        (1, "goodbye moon", 2.0),
    ]
    ph = _seg_rows(db, "segments_phonetic", "alpha")
    assert len(ph) == 2
    assert ph[0]["text"] == "hello world"  # original text stored for snippets


def test_empty_segments_are_skipped(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "a", _make_doc([
        (0.0, 1.0, "SPEAKER_00", "real text"),
        (1.0, 2.0, "SPEAKER_00", "   "),
    ]))
    db.upsert_path(p)
    assert len(_seg_rows(db, "segments_fts", "a")) == 1

    # A blank segment EARLIER in the doc must not shift later indices:
    # segment_index reflects the position in the original document, which
    # jump-to-line in the transcript view depends on.
    p2 = _write(tmp_path, "b", _make_doc([
        (0.0, 1.0, "SPEAKER_00", "   "),
        (1.0, 2.0, "SPEAKER_00", "real text"),
    ]))
    db.upsert_path(p2)
    rows = _seg_rows(db, "segments_fts", "b")
    assert [(r["segment_index"], r["text"]) for r in rows] == [(1, "real text")]


def test_reupsert_replaces_segment_rows(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "a", _make_doc([(0.0, 1.0, "SPEAKER_00", "one"),
                                         (1.0, 2.0, "SPEAKER_00", "two")]))
    db.upsert_path(p)
    _write(tmp_path, "a", _make_doc([(0.0, 1.0, "SPEAKER_00", "only")]))
    db.upsert_path(p)
    rows = _seg_rows(db, "segments_fts", "a")
    assert [(r["segment_index"], r["text"]) for r in rows] == [(0, "only")]
    assert len(_seg_rows(db, "segments_phonetic", "a")) == 1


def test_delete_removes_segment_rows(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "a", _make_doc([(0.0, 1.0, "SPEAKER_00", "hello")]))
    db.upsert_path(p)
    db.delete_by_path(p)
    assert _seg_rows(db, "segments_fts", "a") == []
    assert _seg_rows(db, "segments_phonetic", "a") == []


def test_version_mismatch_drops_and_rebuilds(tmp_path: Path):
    db_path = tmp_path / "library.db"
    db = LibraryDB(db_path)
    p = _write(tmp_path, "a", _make_doc([(0.0, 1.0, "SPEAKER_00", "hello")]))
    db.upsert_path(p)
    # Simulate an old-schema DB by forging a stale version number.
    db._conn.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION - 1,))
    db._conn.commit()
    db.close()

    db2 = LibraryDB(db_path)  # must not raise; must start empty
    assert db2.list() == []
    row = db2._conn.execute("SELECT version FROM schema_version").fetchone()
    assert row[0] == SCHEMA_VERSION
    # And reindexing works on the fresh schema.
    db2.upsert_path(p)
    assert len(db2.list()) == 1
    db2.close()
