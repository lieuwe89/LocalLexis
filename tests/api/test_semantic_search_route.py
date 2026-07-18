from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app
from speechtotext.rag import embedder as rag_embedder


class _FakeEmbedder:
    def embed(self, texts):
        v = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
        return np.repeat(v, len(texts), axis=0)


@pytest.fixture
def client(tmp_path):
    doc = {
        "audio_path": str(tmp_path / "a.mp3"),
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "S", "text": "hallo wereld"}],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (tmp_path / "alpha.json").write_text(json.dumps(doc), encoding="utf-8")
    # Existing test file convention (tests/api/test_routes_transcripts.py): no
    # `with` block, so the app's lifespan (and its real EmbedWorker) never
    # runs. Chunks are normally created by the lifespan's initial sync_dirs
    # thread; do it here directly so pending_chunks() has rows to embed.
    app = create_app(library_db_path=tmp_path / "lib.db")
    app.state.library_dirs.add(tmp_path)
    app.state.library_db.sync_dirs([tmp_path])
    c = TestClient(app)
    return c, app


def _embed_all(db):
    pend = db.pending_chunks(rag_embedder.EMBED_MODEL, limit=100)
    vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    db.store_embeddings(
        rag_embedder.EMBED_MODEL, 3, [(cid, vec.tobytes()) for cid, _ in pend]
    )


def test_semantic_search_returns_hits(client, monkeypatch):
    c, app = client
    monkeypatch.setattr(rag_embedder, "get_embedder", lambda: _FakeEmbedder())
    _embed_all(app.state.library_db)
    r = c.get("/transcripts", params={"q": "groet", "semantic": 1})
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["id"] == "alpha"
    assert items[0]["hits"][0]["segment_index"] == 0


def test_semantic_unavailable_returns_503(client, monkeypatch):
    c, _ = client

    class _Broken:
        def embed(self, texts):
            raise rag_embedder.EmbedderError("embedding model unavailable: x")

    monkeypatch.setattr(rag_embedder, "get_embedder", lambda: _Broken())
    r = c.get("/transcripts", params={"q": "groet", "semantic": 1})
    assert r.status_code == 503


def test_without_semantic_flag_fts_path_unchanged(client):
    c, _ = client
    r = c.get("/transcripts", params={"q": "hallo"})
    assert r.status_code == 200
    assert r.json()[0]["id"] == "alpha"
