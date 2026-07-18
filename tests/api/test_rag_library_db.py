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


def _embed_all(db: LibraryDB, model: str = "test-model"):
    """Deterministic fake embeddings: unit vector keyed on first word."""
    pend = db.pending_chunks(model, limit=1000)
    rows = []
    for cid, text in pend:
        seed = float(len(text.split()[0]))
        v = np.array([seed, 1.0, 0.0], dtype=np.float64)
        v = (v / np.linalg.norm(v)).astype(np.float32)
        rows.append((cid, v.tobytes()))
    db.store_embeddings(model, 3, rows)


def test_reupsert_replaces_chunks_and_drops_embeddings(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "alpha", _make_doc([(0.0, 5.0, "hallo wereld")]))
    db.upsert_path(p)
    cid = _chunk_rows(db, "alpha")[0]["id"]
    vec = np.ones(4, dtype=np.float32)
    db.store_embeddings("m", 4, [(cid, vec.tobytes())])
    # re-upsert → chunks replaced, embedding cascades away
    db.upsert_path(p)
    assert len(_chunk_rows(db, "alpha")) == 1
    n = db._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    assert n == 0


def test_pending_then_store_then_none_pending(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "alpha", _make_doc([(0.0, 5.0, "hallo wereld dit is tekst")]))
    db.upsert_path(p)
    assert len(db.pending_chunks("test-model")) == 1
    _embed_all(db)
    assert db.pending_chunks("test-model") == []


def test_model_change_makes_chunks_pending_again(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "alpha", _make_doc([(0.0, 5.0, "hallo wereld")]))
    db.upsert_path(p)
    _embed_all(db, model="old-model")
    assert len(db.pending_chunks("new-model")) == 1


def test_top_chunks_ranks_by_similarity(db: LibraryDB, tmp_path: Path):
    doc_a = _make_doc([(0.0, 5.0, "kort verhaal")], audio_name="a.mp3")
    doc_b = _make_doc([(0.0, 5.0, "aanzienlijk langer eerste woord hier")], audio_name="b.mp3")
    db.upsert_path(_write(tmp_path, "alpha", doc_a))
    db.upsert_path(_write(tmp_path, "beta", doc_b))
    _embed_all(db)
    # query = exact fake-embedding of "kort" (len 4) → alpha's chunk wins
    q = np.array([4.0, 1.0, 0.0], dtype=np.float64)
    q = (q / np.linalg.norm(q)).astype(np.float32)
    top = db.top_chunks(q, "test-model", k=2)
    assert top[0]["transcript_id"] == "alpha"
    assert top[0]["score"] > top[1]["score"]
    assert "first_segment" in top[0] and "text" in top[0]


def test_semantic_search_groups_hits_per_transcript(db: LibraryDB, tmp_path: Path):
    db.upsert_path(_write(tmp_path, "alpha", _make_doc([(0.0, 5.0, "kort verhaal")])))
    _embed_all(db)
    q = np.array([4.0, 1.0, 0.0], dtype=np.float64)
    q = (q / np.linalg.norm(q)).astype(np.float32)
    items = db.semantic_search(q, "test-model", limit=10)
    assert len(items) == 1
    item = items[0]
    assert item["id"] == "alpha"
    assert item["hits"][0]["segment_index"] == 0
    assert item["hits"][0]["snippet_parts"][0]["text"].startswith("kort")
    assert item["total_hits"] == 1


def test_semantic_search_empty_index_returns_empty(db: LibraryDB):
    q = np.zeros(3, dtype=np.float32)
    assert db.semantic_search(q, "test-model") == []


def test_store_embeddings_invalidates_cache(db: LibraryDB, tmp_path: Path):
    db.upsert_path(_write(tmp_path, "alpha", _make_doc([(0.0, 5.0, "kort verhaal")])))
    _embed_all(db)
    q = np.array([4.0, 1.0, 0.0], dtype=np.float32)
    q = q / np.linalg.norm(q)
    assert len(db.top_chunks(q, "test-model", k=5)) == 1  # warms cache
    db.upsert_path(_write(tmp_path, "beta", _make_doc([(0.0, 5.0, "kort ander")], audio_name="b.mp3")))
    _embed_all(db)
    assert len(db.top_chunks(q, "test-model", k=5)) == 2  # cache rebuilt
