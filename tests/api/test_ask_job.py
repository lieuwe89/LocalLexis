from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

from speechtotext.api import runner as runner_mod
from speechtotext.api.jobs import JobRegistry, JobStatus
from speechtotext.api.library_db import LibraryDB
from speechtotext.rag import embedder as rag_embedder
from speechtotext.summarize.prompt import build_ask_messages


class _FakeEmbedder:
    def embed(self, texts):
        v = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
        return np.repeat(v, len(texts), axis=0)


class _FakeProvider:
    model = "fake-model"

    def chat(self, messages):
        assert any("Question:" in m["content"] for m in messages)
        return "Het antwoord is 42 [1]."


@pytest.fixture
def db(tmp_path: Path) -> LibraryDB:
    d = LibraryDB(tmp_path / "library.db")
    doc = {
        "audio_path": "/x/a.mp3",
        "segments": [{"start": 12.0, "end": 15.0, "speaker": "S", "text": "het antwoord is tweeenveertig"}],
        "created_at": "2026-07-18T12:00:00+00:00",
    }
    p = tmp_path / "alpha.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    d.upsert_path(p)
    vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    pend = d.pending_chunks(rag_embedder.EMBED_MODEL, limit=10)
    d.store_embeddings(rag_embedder.EMBED_MODEL, 3, [(cid, vec.tobytes()) for cid, _ in pend])
    return d


def _wait(registry, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = registry.get(job_id)
        if rec.status in (JobStatus.complete, JobStatus.failed):
            return rec
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_build_ask_messages_numbers_excerpts():
    msgs = build_ask_messages("wat is het antwoord?", [
        {"transcript_id": "alpha", "first_segment": 0, "start": 12.0,
         "text": "het antwoord is 42", "score": 0.9},
    ])
    assert msgs[0]["role"] == "system"
    assert "[1]" in msgs[1]["content"]
    assert "wat is het antwoord?" in msgs[1]["content"]


def test_run_ask_job_sets_result(db, monkeypatch):
    monkeypatch.setattr(rag_embedder, "get_embedder", lambda: _FakeEmbedder())
    monkeypatch.setattr(runner_mod, "_summarize_provider", lambda cfg: _FakeProvider())
    registry = JobRegistry()
    job_id = registry.create(kind="ask")
    runner_mod.run_ask_job(registry, job_id, "wat is het antwoord?", db)
    rec = _wait(registry, job_id)
    assert rec.status == JobStatus.complete
    assert rec.result["answer"].startswith("Het antwoord")
    src = rec.result["sources"][0]
    assert src["transcript_id"] == "alpha"
    assert src["segment_index"] == 0
    assert src["start"] == 12.0


def test_run_ask_job_empty_index_fails_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_embedder, "get_embedder", lambda: _FakeEmbedder())
    empty = LibraryDB(tmp_path / "empty.db")
    registry = JobRegistry()
    job_id = registry.create(kind="ask")
    runner_mod.run_ask_job(registry, job_id, "iets?", empty)
    rec = _wait(registry, job_id)
    assert rec.status == JobStatus.failed
    assert "index" in (rec.error or "").lower()
