from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

from speechtotext.api import embed_worker as mod
from speechtotext.api.library_db import LibraryDB
from speechtotext.rag.embedder import EMBED_MODEL


class _FakeEmbedder:
    def embed(self, texts):
        return np.ones((len(texts), 4), dtype=np.float32)


@pytest.fixture
def db(tmp_path: Path) -> LibraryDB:
    d = LibraryDB(tmp_path / "library.db")
    doc = {
        "audio_path": "/x/a.mp3",
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "S", "text": "hallo wereld"}],
        "created_at": "2026-07-18T12:00:00+00:00",
    }
    p = tmp_path / "alpha.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    d.upsert_path(p)
    return d


def test_drain_embeds_pending(db, monkeypatch):
    monkeypatch.setattr(mod, "get_embedder", lambda: _FakeEmbedder())
    w = mod.EmbedWorker(db)
    assert w._drain() is True          # embedded one batch
    assert w._drain() is False         # nothing left
    assert db.pending_chunks(EMBED_MODEL) == []


def test_worker_thread_drains_on_poke(db, monkeypatch):
    monkeypatch.setattr(mod, "get_embedder", lambda: _FakeEmbedder())
    w = mod.EmbedWorker(db)
    w.start()
    try:
        w.poke()
        deadline = time.time() + 5
        while db.pending_chunks(EMBED_MODEL) and time.time() < deadline:
            time.sleep(0.02)
        assert db.pending_chunks(EMBED_MODEL) == []
    finally:
        w.stop()
