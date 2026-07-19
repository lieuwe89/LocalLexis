"""Joined laptops proxy /library/ask to the hub (Task 9 of the hub-as-SSOT
plan): the hub holds the full library + the LLM. The local process records
the hub's job id on a LOCAL JobRecord and GET /jobs/{id} transparently
proxies status+result from the hub, so the existing AskPanel polling works
unchanged. Non-joined laptops keep running ask jobs locally.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from speechtotext.api import runner as runner_mod
from speechtotext.api.app import create_app
from speechtotext.client import identity as identity_module
from speechtotext.client import state as state_module
from speechtotext.client.hub_client import HubClient
from speechtotext.client.state import ClientState
from speechtotext.rag import embedder as rag_embedder


def _join_fake_hub():
    """Fake a joined-to-hub state on disk (isolated per-test app-data dir
    via tests/api/conftest.py's autouse fixture), same fields used by
    tests/client/test_state.py and test_semantic_proxy.py."""
    identity_module.generate()
    state_module.save(ClientState(
        hub_url="http://hub.example",
        workspace_id="ws-x",
        device_id="dev-1",
        device_name="laptop",
        tls_spki_b64=None,
        cursor=0.0,
    ))


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


def _poll(c, job_id, timeout=5.0):
    deadline = time.time() + timeout
    rec = None
    while time.time() < deadline:
        rec = c.get(f"/jobs/{job_id}").json()
        if rec["status"] in ("complete", "failed"):
            return rec
        time.sleep(0.02)
    raise AssertionError(f"job did not finish: {rec}")


def test_joined_ask_forwards_and_proxies_job(client, monkeypatch):
    c, app = client
    _join_fake_hub()

    def fake_post_json(self, path, body):
        assert path == "/library/ask"
        assert body == {"question": "wat?"}
        return {"job_id": "h1"}

    def fake_get_json(self, path_with_query):
        assert path_with_query == "/jobs/h1"
        return {
            "id": "h1", "status": "complete", "stage": "ask",
            "percent": 1.0, "error": None,
            "result": {"answer": "A", "sources": []},
        }

    monkeypatch.setattr(HubClient, "post_json", fake_post_json)
    monkeypatch.setattr(HubClient, "get_json", fake_get_json)

    r = c.post("/library/ask", json={"question": "wat?"})
    assert r.status_code == 202, r.text
    local_job_id = r.json()["job_id"]
    assert local_job_id != "h1"

    rec = _poll(c, local_job_id)
    assert rec["id"] == local_job_id
    assert rec["status"] == "complete"
    assert rec["result"] == {"answer": "A", "sources": []}


def test_joined_ask_hub_down_503_on_submit(client, monkeypatch):
    c, app = client
    _join_fake_hub()

    def fake_post_json(self, path, body):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(HubClient, "post_json", fake_post_json)

    r = c.post("/library/ask", json={"question": "wat?"})
    assert r.status_code == 503
    assert "hub" in r.json()["detail"].lower()


def test_proxy_poll_hub_down_fails_job(client, monkeypatch):
    c, app = client
    _join_fake_hub()

    def fake_post_json(self, path, body):
        return {"job_id": "h1"}

    def fake_get_json(self, path_with_query):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(HubClient, "post_json", fake_post_json)
    monkeypatch.setattr(HubClient, "get_json", fake_get_json)

    r = c.post("/library/ask", json={"question": "wat?"})
    assert r.status_code == 202, r.text
    local_job_id = r.json()["job_id"]

    rec = _poll(c, local_job_id)
    assert rec["status"] == "failed"
    assert "hub" in (rec["error"] or "").lower()


def test_not_joined_ask_stays_local(client, monkeypatch):
    c, app = client
    monkeypatch.setattr(rag_embedder, "get_embedder", lambda: _FakeEmbedder())
    _embed_all(app.state.library_db)
    monkeypatch.setattr(runner_mod, "_summarize_provider", lambda cfg: _FakeProvider())

    r = c.post("/library/ask", json={"question": "wat?"})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]

    rec = _poll(c, job_id)
    assert rec["status"] == "complete"
    assert rec["result"]["answer"] == "Antwoord."
    assert rec["result"]["sources"][0]["transcript_id"] == "alpha"


def test_self_joined_ask_falls_back_to_local(tmp_path, monkeypatch):
    """A process that is simultaneously joined AND its own hub (loopback
    transport, same pattern as test_semantic_proxy.py's
    test_self_joined_semantic_no_recursion) must not recurse: the forwarded
    ask hits the same app, which detects the in-progress forward and runs
    the ask job locally instead."""
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

        monkeypatch.setattr(rag_embedder, "get_embedder", lambda: _FakeEmbedder())
        _embed_all(app.state.library_db)
        monkeypatch.setattr(runner_mod, "_summarize_provider", lambda cfg: _FakeProvider())

        r = c.post("/library/ask", json={"question": "wat?"})
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]

        rec = _poll(c, job_id)
        assert rec["status"] == "complete", rec
        assert rec["result"]["answer"] == "Antwoord."
    finally:
        routes_client._TEST_TRANSPORT = None
