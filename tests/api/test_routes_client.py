import base64
import json

from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


def _client(tmp_path):
    app = create_app(library_db_path=tmp_path / "lib.db")
    return app, TestClient(app)


def test_hub_status_not_joined(tmp_path):
    _, client = _client(tmp_path)
    resp = client.get("/client/hub")
    assert resp.status_code == 200
    assert resp.json() == {"joined": False}


def test_join_against_self_and_status_and_leave(tmp_path):
    # The app under test is both hub and client: mint a token on it,
    # join it via loopback pairing, then verify status flips.
    app, client = _client(tmp_path)
    tok = client.post("/pair/tokens").json()["token"]
    payload = base64.b64encode(json.dumps({
        "hub_url": str(client.base_url),
        "workspace_id": "ws-x",
        "token": tok,
    }).encode()).decode()

    import httpx
    from speechtotext.api import routes_client
    routes_client._TEST_TRANSPORT = httpx.ASGITransport(app=app)
    try:
        resp = client.post("/client/hub/join", json={
            "pairing_string": payload, "device_name": "test-laptop",
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["joined"] is True
        assert body["device_id"].startswith("dev-")

        status = client.get("/client/hub").json()
        assert status["joined"] is True
        assert status["pending_uploads"] == 0

        resp = client.post("/client/hub/leave")
        assert resp.status_code == 200
        assert client.get("/client/hub").json() == {"joined": False}
    finally:
        routes_client._TEST_TRANSPORT = None


def test_join_twice_is_conflict(tmp_path):
    app, client = _client(tmp_path)
    tok = client.post("/pair/tokens").json()["token"]
    payload = base64.b64encode(json.dumps({
        "hub_url": str(client.base_url), "workspace_id": "ws-x", "token": tok,
    }).encode()).decode()
    import httpx
    from speechtotext.api import routes_client
    routes_client._TEST_TRANSPORT = httpx.ASGITransport(app=app)
    try:
        assert client.post("/client/hub/join", json={
            "pairing_string": payload, "device_name": "x"}).status_code == 200
        # second join without leaving -> 409, and must NOT have clobbered identity
        tok2 = client.post("/pair/tokens").json()["token"]
        payload2 = base64.b64encode(json.dumps({
            "hub_url": str(client.base_url), "workspace_id": "ws-x", "token": tok2,
        }).encode()).decode()
        r = client.post("/client/hub/join", json={
            "pairing_string": payload2, "device_name": "y"})
        assert r.status_code == 409
        assert client.get("/client/hub").json()["joined"] is True
    finally:
        routes_client._TEST_TRANSPORT = None


def test_join_with_bad_pairing_string_is_400(tmp_path):
    _, client = _client(tmp_path)
    resp = client.post("/client/hub/join", json={
        "pairing_string": "garbage", "device_name": "x",
    })
    assert resp.status_code == 400


def test_transcribe_routes_to_outbox_when_joined(tmp_path):
    app, client = _client(tmp_path)
    tok = client.post("/pair/tokens").json()["token"]
    payload = base64.b64encode(json.dumps({
        "hub_url": str(client.base_url), "workspace_id": "ws-x", "token": tok,
    }).encode()).decode()

    import httpx
    from speechtotext.api import routes_client
    routes_client._TEST_TRANSPORT = httpx.ASGITransport(app=app)
    try:
        client.post("/client/hub/join", json={
            "pairing_string": payload, "device_name": "x",
        })
        audio = tmp_path / "drop.wav"
        audio.write_bytes(b"RIFF" + b"\x00" * 64)
        resp = client.post("/jobs/transcribe", json={"path": str(audio)})
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        job = client.get(f"/jobs/{job_id}").json()
        assert job["kind"] == "hub_upload"
        assert client.get("/client/hub").json()["pending_uploads"] == 1
    finally:
        routes_client._TEST_TRANSPORT = None
