"""Joined laptops proxy semantic search to the hub instead of embedding
locally (Task 8 of the hub-as-SSOT plan): the hub holds the full library
and the embedding model, and transcript ids match the synced copies so
jump-to-segment keeps working. Non-semantic search must stay local (FTS
over the merged library) even when joined.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app
from speechtotext.client import identity as identity_module
from speechtotext.client import state as state_module
from speechtotext.client.hub_client import HubClient
from speechtotext.client.state import ClientState
from speechtotext.rag import embedder as rag_embedder


def _join_fake_hub():
    """Fake a joined-to-hub state on disk (isolated per-test app-data dir
    via tests/api/conftest.py's autouse fixture), same fields used by
    tests/client/test_state.py."""
    identity_module.generate()
    state_module.save(ClientState(
        hub_url="http://hub.example",
        workspace_id="ws-x",
        device_id="dev-1",
        device_name="laptop",
        tls_spki_b64=None,
        cursor=0.0,
    ))


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


def test_joined_semantic_forwards_to_hub(client, monkeypatch):
    c, app = client
    _join_fake_hub()

    recorded = {}

    def fake_get_json(self, path_with_query):
        recorded["path"] = path_with_query
        return [{"id": "alpha", "hits": []}]

    monkeypatch.setattr(HubClient, "get_json", fake_get_json)

    def _boom():
        raise AssertionError("local embedder must not be used when joined")

    monkeypatch.setattr(rag_embedder, "get_embedder", _boom)

    r = c.get("/transcripts", params={"q": "x", "semantic": 1})
    assert r.status_code == 200, r.text
    assert r.json() == [{"id": "alpha", "hits": []}]
    assert "q=x" in recorded["path"]
    assert "semantic=1" in recorded["path"]
    assert "limit=" in recorded["path"]


def test_joined_semantic_hub_down_503(client, monkeypatch):
    c, app = client
    _join_fake_hub()

    def fake_get_json(self, path_with_query):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(HubClient, "get_json", fake_get_json)

    r = c.get("/transcripts", params={"q": "x", "semantic": 1})
    assert r.status_code == 503
    assert "hub" in r.json()["detail"].lower()


def test_not_joined_semantic_stays_local(client, monkeypatch):
    c, app = client

    class _FakeEmbedder:
        def embed(self, texts):
            v = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
            return np.repeat(v, len(texts), axis=0)

    monkeypatch.setattr(rag_embedder, "get_embedder", lambda: _FakeEmbedder())
    pend = app.state.library_db.pending_chunks(rag_embedder.EMBED_MODEL, limit=100)
    vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    app.state.library_db.store_embeddings(
        rag_embedder.EMBED_MODEL, 3, [(cid, vec.tobytes()) for cid, _ in pend]
    )
    r = c.get("/transcripts", params={"q": "groet", "semantic": 1})
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["id"] == "alpha"


def test_self_joined_semantic_no_recursion(tmp_path, monkeypatch):
    """A process that is simultaneously joined AND its own hub (loopback
    transport, same setup as test_relabel_hub_origin.py) must not recurse:
    the forwarded query hits the same app, which detects the in-progress
    forward and answers via the local embed path instead."""
    import base64

    from speechtotext.api import routes_client

    doc = {
        "audio_path": str(tmp_path / "a.mp3"),
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "S", "text": "hallo wereld"}],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (tmp_path / "alpha.json").write_text(json.dumps(doc), encoding="utf-8")
    app = create_app(library_db_path=tmp_path / "lib.db")
    c = TestClient(app)
    routes_client._TEST_TRANSPORT = httpx.ASGITransport(app=app)
    try:
        tok = c.post("/pair/tokens").json()["token"]
        payload = base64.b64encode(json.dumps({
            "hub_url": str(c.base_url), "workspace_id": "ws-x", "token": tok,
        }).encode()).decode()
        resp = c.post("/client/hub/join", json={
            "pairing_string": payload, "device_name": "laptop"})
        assert resp.status_code == 200, resp.text

        app.state.library_dirs.add(tmp_path)
        app.state.library_db.sync_dirs([tmp_path])

        class _FakeEmbedder:
            def embed(self, texts):
                v = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
                return np.repeat(v, len(texts), axis=0)

        monkeypatch.setattr(rag_embedder, "get_embedder", lambda: _FakeEmbedder())
        pend = app.state.library_db.pending_chunks(rag_embedder.EMBED_MODEL, limit=100)
        vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        app.state.library_db.store_embeddings(
            rag_embedder.EMBED_MODEL, 3, [(cid, vec.tobytes()) for cid, _ in pend]
        )

        r = c.get("/transcripts", params={"q": "groet", "semantic": 1})
        assert r.status_code == 200, r.text
        assert r.json()[0]["id"] == "alpha"
    finally:
        routes_client._TEST_TRANSPORT = None


def test_joined_non_semantic_search_stays_local(client):
    """Even when joined, a plain (non-semantic) query hits the merged
    local FTS index, not the hub — only semantic=1 forwards."""
    c, app = client
    _join_fake_hub()
    r = c.get("/transcripts", params={"q": "hallo"})
    assert r.status_code == 200
    assert r.json()[0]["id"] == "alpha"
