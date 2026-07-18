"""Chunk + embedding storage and semantic search in LibraryDB."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from speechtotext.api.library_db import LibraryDB


def _make_doc(text_segments, audio_name: str = "meeting.mp3") -> dict:
    return {
        "version": 1,
        "audio_path": f"/some/dir/{audio_name}",
        "duration_seconds": text_segments[-1][1] if text_segments else 0.0,
        "language": "nl",
        "speakers": {"SPEAKER_00": "Alice"},
        "segments": [
            {"start": s, "end": e, "speaker": "SPEAKER_00", "text": t}
            for s, e, t in text_segments
        ],
        "models": {"asr": "faster-whisper:base"},
        "created_at": "2026-07-18T12:00:00+00:00",
    }


def _write(dir: Path, name: str, doc: dict) -> Path:
    p = dir / f"{name}.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


@pytest.fixture
def db(tmp_path: Path) -> LibraryDB:
    return LibraryDB(tmp_path / "library.db")


def _chunk_rows(db: LibraryDB, tid: str):
    return db._conn.execute(
        "SELECT * FROM chunks WHERE transcript_id=? ORDER BY idx", (tid,)
    ).fetchall()


def test_upsert_writes_chunks(db: LibraryDB, tmp_path: Path):
    long = " ".join(["woord"] * 200)
    p = _write(tmp_path, "alpha", _make_doc([(0.0, 5.0, long), (5.0, 9.0, long)]))
    db.upsert_path(p)
    rows = _chunk_rows(db, "alpha")
    assert len(rows) == 2
    assert rows[0]["first_segment"] == 0
    assert rows[1]["first_segment"] == 1
    assert rows[0]["text"].startswith("woord")
