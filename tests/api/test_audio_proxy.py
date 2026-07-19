"""Migrated transcripts keep their audio on the hub; the laptop's
``GET /transcripts/{tid}/audio`` must stream it through (Range passthrough)
when the local file doesn't exist and this device is joined (Task 4 of the
UX-polish plan). Fixtures mirror tests/api/test_semantic_proxy.py.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app
from speechtotext.client import identity as identity_module
from speechtotext.client import state as state_module
from speechtotext.client.hub_client import HubClient
from speechtotext.client.state import ClientState


def _join_fake_hub():
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
    """Doc whose audio_path points at a file that doesn't exist locally
    (the migrated-transcript case: audio lives on the hub only)."""
    missing_audio = tmp_path / "missing.flac"
    doc = {
        "audio_path": str(missing_audio),
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "S", "text": "hi"}],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (tmp_path / "alpha.json").write_text(json.dumps(doc), encoding="utf-8")
    app = create_app(library_db_path=tmp_path / "lib.db")
    app.state.library_dirs.add(tmp_path)
    app.state.library_db.sync_dirs([tmp_path])
    c = TestClient(app)
    return c, app


def _fake_response(status_code, headers, content):
    return httpx.Response(status_code, headers=headers, content=content)


def test_missing_audio_joined_streams_from_hub(client, monkeypatch):
    c, app = client
    _join_fake_hub()

    def fake_stream_get(self, path_with_query, extra_headers=None):
        return _fake_response(
            200,
            {"content-type": "audio/flac", "accept-ranges": "bytes"},
            b"FAKEAUDIO",
        )

    monkeypatch.setattr(HubClient, "stream_get", fake_stream_get)

    r = c.get("/transcripts/alpha/audio")
    assert r.status_code == 200, r.text
    assert r.content == b"FAKEAUDIO"
    assert r.headers["content-type"] == "audio/flac"


def test_range_forwarded_and_206_passed_through(client, monkeypatch):
    c, app = client
    _join_fake_hub()

    recorded = {}

    def fake_stream_get(self, path_with_query, extra_headers=None):
        recorded["extra_headers"] = extra_headers
        return _fake_response(
            206,
            {
                "content-type": "audio/flac",
                "content-range": "bytes 0-3/9",
                "accept-ranges": "bytes",
            },
            b"FAKE",
        )

    monkeypatch.setattr(HubClient, "stream_get", fake_stream_get)

    r = c.get("/transcripts/alpha/audio", headers={"Range": "bytes=0-3"})
    assert r.status_code == 206, r.text
    assert r.content == b"FAKE"
    assert r.headers["content-range"] == "bytes 0-3/9"
    assert recorded["extra_headers"] == {"Range": "bytes=0-3"}


def test_hub_down_503(client, monkeypatch):
    c, app = client
    _join_fake_hub()

    def fake_stream_get(self, path_with_query, extra_headers=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(HubClient, "stream_get", fake_stream_get)

    r = c.get("/transcripts/alpha/audio")
    assert r.status_code == 503
    assert "hub" in r.json()["detail"].lower()


def test_hub_404_passed_through(client, monkeypatch):
    c, app = client
    _join_fake_hub()

    def fake_stream_get(self, path_with_query, extra_headers=None):
        return _fake_response(404, {}, b"")

    monkeypatch.setattr(HubClient, "stream_get", fake_stream_get)

    r = c.get("/transcripts/alpha/audio")
    assert r.status_code == 404


def test_local_file_present_no_proxy(tmp_path, monkeypatch):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFFDATA")
    doc = {
        "audio_path": str(audio),
        "segments": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (tmp_path / "alpha.json").write_text(json.dumps(doc), encoding="utf-8")
    app = create_app(library_db_path=tmp_path / "lib.db")
    app.state.library_dirs.add(tmp_path)
    app.state.library_db.sync_dirs([tmp_path])
    c = TestClient(app)
    _join_fake_hub()

    def _boom(self, path_with_query, extra_headers=None):
        raise AssertionError("hub must not be contacted when local file exists")

    monkeypatch.setattr(HubClient, "stream_get", _boom)

    r = c.get("/transcripts/alpha/audio")
    assert r.status_code == 200
    assert r.content == b"RIFFDATA"


def test_not_joined_missing_audio_404(client):
    c, app = client
    r = c.get("/transcripts/alpha/audio")
    assert r.status_code == 404


def test_self_joined_no_recursion(tmp_path):
    """A process that is simultaneously joined AND its own hub (loopback
    transport) must not recurse when the audio is ALSO missing locally on
    the hub side: the inner forward guard trips and the hub-side handler
    404s locally instead of forwarding again."""
    from speechtotext.api import routes_client

    missing_audio = tmp_path / "missing.flac"
    doc = {
        "audio_path": str(missing_audio),
        "segments": [],
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

        r = c.get("/transcripts/alpha/audio")
        assert r.status_code == 404, r.text
    finally:
        routes_client._TEST_TRANSPORT = None
