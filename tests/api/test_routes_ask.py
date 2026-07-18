from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

from speechtotext.api import runner as runner_mod
from speechtotext.api.app import create_app
from speechtotext.rag import embedder as rag_embedder


class _FakeEmbedder:
    def embed(self, texts):
        v = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
        return np.repeat(v, len(texts), axis=0)


class _FakeProvider:
    model = "fake-model"

    def chat(self, messages):
        return "Antwoord."


@pytest.fixture
def client(tmp_path):
    doc = {
        "audio_path": str(tmp_path / "a.mp3"),
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "S", "text": "hallo wereld"}],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (tmp_path / "alpha.json").write_text(json.dumps(doc), encoding="utf-8")
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


def test_ask_returns_job_and_result(client, monkeypatch):
    c, app = client
    monkeypatch.setattr(rag_embedder, "get_embedder", lambda: _FakeEmbedder())
    _embed_all(app.state.library_db)
    monkeypatch.setattr(runner_mod, "_summarize_provider", lambda cfg: _FakeProvider())

    r = c.post("/library/ask", json={"question": "wat?"})
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    rec = None
    for _ in range(100):
        rec = c.get(f"/jobs/{job_id}").json()
        if rec["status"] in ("complete", "failed"):
            break
        time.sleep(0.05)
    assert rec["status"] == "complete"
    assert rec["result"]["answer"] == "Antwoord."
    assert rec["result"]["sources"][0]["transcript_id"] == "alpha"


def test_ask_validates_question(client):
    c, _ = client
    assert c.post("/library/ask", json={"question": ""}).status_code == 422
    assert c.post("/library/ask", json={}).status_code == 422
