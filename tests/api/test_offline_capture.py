"""Tests for POST /client/hub/offline-capture and HubRuntime.hub_reachable."""
import base64
import json

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
