"""Tests for POST /client/hub/offline-capture and HubRuntime.hub_reachable."""
import base64
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app
from speechtotext.client.hub_runtime import HubRuntime


@pytest.fixture()
def hub(tmp_path):
    from speechtotext.api import routes_client

    app = create_app(library_db_path=tmp_path / "hub-lib.db")
    client = TestClient(app)
    routes_client._TEST_TRANSPORT = httpx.ASGITransport(app=app)
    yield app, client
    routes_client._TEST_TRANSPORT = None


def _pair(hub_client, ws="ws-offline-capture"):
    from speechtotext.api import routes_client
    from speechtotext.client import join

    tok = hub_client.post("/pair/tokens").json()["token"]
    pairing = base64.b64encode(json.dumps({
        "hub_url": str(hub_client.base_url),
        "workspace_id": ws,
        "token": tok,
    }).encode()).decode()
    return join.join_hub(
        pairing, device_name="e2e-laptop",
        transport=routes_client.sync_test_transport(),
    )


def test_set_offline_capture_roundtrip(hub):
    _, hub_client = hub
    _pair(hub_client)

    resp = hub_client.post("/client/hub/offline-capture", json={"mode": "queue"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"offline_capture": "queue"}
    assert hub_client.get("/client/hub").json()["offline_capture"] == "queue"

    resp = hub_client.post("/client/hub/offline-capture", json={"mode": "local"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"offline_capture": "local"}
    assert hub_client.get("/client/hub").json()["offline_capture"] == "local"


def test_set_offline_capture_invalid_mode(hub):
    _, hub_client = hub
    _pair(hub_client, ws="ws-invalid-mode")

    resp = hub_client.post("/client/hub/offline-capture", json={"mode": "sometimes"})
    assert resp.status_code == 422


def test_set_offline_capture_409_when_not_joined(tmp_path):
    app = create_app(library_db_path=tmp_path / "lib.db")
    client = TestClient(app)
    resp = client.post("/client/hub/offline-capture", json={"mode": "queue"})
    assert resp.status_code == 409


def test_hub_reachable_any_response_counts(monkeypatch, tmp_path):
    from speechtotext.client import state as state_module

    monkeypatch.setattr(
        state_module, "load",
        lambda: state_module.ClientState(
            hub_url="http://hub.example",
            workspace_id="ws",
            device_id="dev-1",
            device_name="laptop",
            tls_spki_b64=None,
            cursor=0.0,
        ),
    )
    runtime = HubRuntime()

    import httpx as httpx_module

    def fake_get_401(url, timeout=None):
        return httpx_module.Response(401, request=httpx_module.Request("GET", url))
    monkeypatch.setattr(httpx_module, "get", fake_get_401)
    assert runtime.hub_reachable() is True

    def fake_get_connect_error(url, timeout=None):
        raise httpx_module.ConnectError("boom")
    monkeypatch.setattr(httpx_module, "get", fake_get_connect_error)
    assert runtime.hub_reachable() is False

    def fake_get_timeout(url, timeout=None):
        raise httpx_module.ConnectTimeout("boom")
    monkeypatch.setattr(httpx_module, "get", fake_get_timeout)
    assert runtime.hub_reachable() is False

    monkeypatch.setattr(state_module, "load", lambda: None)
    assert runtime.hub_reachable() is False


def _set_mode(hub_client, mode: str) -> None:
    resp = hub_client.post("/client/hub/offline-capture", json={"mode": mode})
    assert resp.status_code == 200, resp.text


def test_offline_local_mode_falls_back_to_local_transcribe(hub, tmp_path, monkeypatch):
    app, hub_client = hub
    _pair(hub_client, ws="ws-local-fallback")
    _set_mode(hub_client, "local")

    monkeypatch.setattr(app.state.hub_runtime, "hub_reachable", lambda timeout=1.0: False)
    from unittest.mock import MagicMock
    fake_run = MagicMock()
    monkeypatch.setattr("speechtotext.api.runner.run_transcribe_job", fake_run)

    audio = tmp_path / "x.wav"
    audio.write_bytes(b"RIFF00")
    resp = hub_client.post("/jobs/transcribe", json={"path": str(audio)})
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]

    rec = app.state.jobs.get(job_id)
    assert rec.kind == "transcribe"
    fake_run.assert_called_once()


def test_offline_queue_mode_still_queues(hub, tmp_path, monkeypatch):
    app, hub_client = hub
    _pair(hub_client, ws="ws-queue-mode")
    _set_mode(hub_client, "queue")

    calls = []
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: calls.append((a, kw)))

    audio = tmp_path / "x.wav"
    audio.write_bytes(b"RIFF00")
    resp = hub_client.post("/jobs/transcribe", json={"path": str(audio)})
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]

    rec = app.state.jobs.get(job_id)
    assert rec.kind == "hub_upload"
    assert calls == []  # queue mode must not probe hub_reachable at all


def test_online_always_routes_to_hub(hub, tmp_path, monkeypatch):
    app, hub_client = hub
    _pair(hub_client, ws="ws-online-routes")
    _set_mode(hub_client, "local")

    monkeypatch.setattr(app.state.hub_runtime, "hub_reachable", lambda timeout=1.0: True)

    audio = tmp_path / "x.wav"
    audio.write_bytes(b"RIFF00")
    resp = hub_client.post("/jobs/transcribe", json={"path": str(audio)})
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]

    rec = app.state.jobs.get(job_id)
    assert rec.kind == "hub_upload"


def test_runtime_sweep_migrates_local_rows_after_migration(monkeypatch):
    from speechtotext.client import hub_runtime as hub_runtime_module
    from speechtotext.client import identity as identity_module
    from speechtotext.client import state as state_module

    identity_module.generate()
    st = state_module.ClientState(
        hub_url="http://hub:8010", workspace_id="ws", device_id="dev-1",
        device_name="laptop", tls_spki_b64=None, cursor=100.0,
    )
    state_module.save(st)

    class FakeHubClient:
        def close(self):
            pass

    fake_client = FakeHubClient()
    monkeypatch.setattr(hub_runtime_module.upload_queue, "sweep", lambda client: [])
    monkeypatch.setattr(hub_runtime_module.sync_puller, "pull_once", lambda client: [])

    swept_with = []
    rt = hub_runtime_module.HubRuntime(
        hub_client_factory=lambda st, ident: fake_client,
        on_local_sweep=lambda client: swept_with.append(client),
        period_s=3600.0,
    )
    rt.start()
    try:
        rt.poke()
        deadline = time.time() + 5.0
        while time.time() < deadline and not swept_with:
            time.sleep(0.02)
        assert swept_with == []  # migrated_at is None -> sweep must not fire
    finally:
        rt.stop()

    state_module.update_fields(migrated_at=123.0)
    swept_with_2 = []
    rt2 = hub_runtime_module.HubRuntime(
        hub_client_factory=lambda st, ident: fake_client,
        on_local_sweep=lambda client: swept_with_2.append(client),
        period_s=3600.0,
    )
    # migrated_at is already set before start(), so the runtime's very
    # first cycle (no poke needed) should sweep — don't also poke, or a
    # second redundant cycle races the first and double-appends.
    rt2.start()
    try:
        deadline = time.time() + 5.0
        while time.time() < deadline and not swept_with_2:
            time.sleep(0.02)
        assert swept_with_2 == [fake_client]
    finally:
        rt2.stop()
