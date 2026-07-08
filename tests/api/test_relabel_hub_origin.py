import base64
import json

from fastapi.testclient import TestClient

from speechtotext.api.app import create_app
from tests.api._signing import signed_headers


def _joined_app(tmp_path):
    """One app instance acting as both hub and joined client, with the
    sync wrapper looping outbound signed calls back into itself."""
    import httpx
    from speechtotext.api import routes_client

    app = create_app(library_db_path=tmp_path / "lib.db")
    client = TestClient(app)
    routes_client._TEST_TRANSPORT = httpx.ASGITransport(app=app)
    tok = client.post("/pair/tokens").json()["token"]
    payload = base64.b64encode(json.dumps({
        "hub_url": str(client.base_url), "workspace_id": "ws-x", "token": tok,
    }).encode()).decode()
    resp = client.post("/client/hub/join", json={
        "pairing_string": payload, "device_name": "laptop"})
    assert resp.status_code == 200, resp.text
    return app, client


def _plant_hub_doc(app, tid="t1"):
    from speechtotext.client.paths import synced_dir
    d = synced_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{tid}.json").write_text(json.dumps({
        "audio_path": "/x/a.wav",
        "segments": [{"speaker": "SPEAKER_00", "text": "hi"}],
        "speakers": {"SPEAKER_00": "SPEAKER_00"},
        "_clocks": {},
        "_history": [],
    }), encoding="utf-8")
    app.state.library_dirs.add(d)
    app.state.library_db.sync_dirs([d])
    return d / f"{tid}.json"


def test_relabel_hub_origin_forwards_crdt_op(tmp_path):
    from speechtotext.api import routes_client
    app, client = _joined_app(tmp_path)
    try:
        doc_path = _plant_hub_doc(app)
        resp = client.patch("/transcripts/t1/relabel",
                            json={"SPEAKER_00": "Alice"})
        assert resp.status_code == 200, resp.text
        # The forward applied the CRDT op on the hub's copy (same file in
        # this loopback-self setup): speakers now shows the new name and a
        # clock entry exists.
        doc = json.loads(doc_path.read_text())
        assert doc["speakers"]["SPEAKER_00"] == "Alice"
        assert "speakers.SPEAKER_00" in doc["_clocks"]
        assert doc["_history"]  # op recorded
    finally:
        routes_client._TEST_TRANSPORT = None


def test_relabel_forward_hub_error_is_502(tmp_path, monkeypatch):
    """A hub error during the forward surfaces as a clean 502, not an
    uncaught 500 leaking an httpx stack trace to the UI."""
    import httpx

    from speechtotext.api import routes_client
    from speechtotext.client.hub_client import HubClient

    app, client = _joined_app(tmp_path)
    try:
        _plant_hub_doc(app)

        def boom(self, path, body):
            req = httpx.Request("PATCH", "http://hub" + path)
            resp = httpx.Response(500, request=req)
            raise httpx.HTTPStatusError("hub boom", request=req, response=resp)

        monkeypatch.setattr(HubClient, "patch_json", boom)
        resp = client.patch("/transcripts/t1/relabel",
                            json={"SPEAKER_00": "Alice"})
        assert resp.status_code == 502, resp.text
    finally:
        routes_client._TEST_TRANSPORT = None


def _pair_device(client, name: str = "test-device"):
    """Pair a fresh device against ``client``. Returns (signing_key, device_id)."""
    from nacl.signing import SigningKey

    token = client.post("/pair/tokens").json()["token"]
    sk = SigningKey.generate()
    r = client.post(
        "/pair",
        json={
            "token": token,
            "device_pubkey_b64": base64.b64encode(
                bytes(sk.verify_key)
            ).decode("ascii"),
            "device_name": name,
        },
    )
    assert r.status_code == 200, r.text
    return sk, r.json()["device_id"]


def _signed_patch(client, sk, device_id, path, body):
    """PATCH ``path`` with a body signed by ``sk`` as ``device_id``."""
    body_bytes = json.dumps(body).encode("utf-8")
    return client.patch(
        path,
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            **signed_headers(sk, device_id, "PATCH", path, body_bytes),
        },
    )


def test_patch_op_hub_origin_forwards_set_title(tmp_path):
    """PATCH /transcripts/{tid} with a set_title op on a hub-synced
    transcript is forwarded to the hub (_forward_op_to_hub), not applied
    via the local read-modify-write branch."""
    from speechtotext.api import routes_client
    app, client = _joined_app(tmp_path)
    try:
        doc_path = _plant_hub_doc(app)
        sk, device_id = _pair_device(client)
        resp = _signed_patch(
            client, sk, device_id, "/transcripts/t1",
            {"op": "set_title", "key": "title", "value": "Renamed",
             "lamport_observed": 0},
        )
        assert resp.status_code == 200, resp.text
        # The forward applied the CRDT op on the hub's copy (same file in
        # this loopback-self setup): title now reflects the new value and
        # the op was recorded via the forward path (clock + history).
        doc = json.loads(doc_path.read_text())
        assert doc["title"] == "Renamed"
        assert "title" in doc["_clocks"]
        assert doc["_history"]  # op recorded
    finally:
        routes_client._TEST_TRANSPORT = None


def test_patch_op_hub_origin_forwards_edit_segment(tmp_path):
    """PATCH /transcripts/{tid} with an edit_segment op on a hub-synced
    transcript is forwarded to the hub (_forward_op_to_hub), not applied
    via the local read-modify-write branch."""
    from speechtotext.api import routes_client
    app, client = _joined_app(tmp_path)
    try:
        doc_path = _plant_hub_doc(app)
        sk, device_id = _pair_device(client)
        resp = _signed_patch(
            client, sk, device_id, "/transcripts/t1",
            {"op": "edit_segment", "key": "segments.0.text",
             "value": "corrected", "lamport_observed": 0},
        )
        assert resp.status_code == 200, resp.text
        doc = json.loads(doc_path.read_text())
        assert doc["segments"][0]["text"] == "corrected"
        assert "segments.0.text" in doc["_clocks"]
        assert doc["_history"]  # op recorded
    finally:
        routes_client._TEST_TRANSPORT = None


def test_relabel_local_origin_stays_local(tmp_path):
    """A transcript NOT under synced_dir is relabeled locally even when
    joined — no forward, existing behavior."""
    from speechtotext.api import routes_client
    app, client = _joined_app(tmp_path)
    try:
        out = tmp_path / "out"
        out.mkdir()
        local = out / "loc1.json"
        # relabel() loads a full Transcript, so the local (non-synced)
        # doc must carry the fields the local writer path expects.
        local.write_text(json.dumps({
            "audio_path": "/x/b.wav",
            "duration_seconds": 1.0,
            "language": "en",
            "created_at": "2026-01-01T00:00:00",
            "speakers": {"SPEAKER_00": "SPEAKER_00"},
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "yo", "speaker": "SPEAKER_00"}
            ],
        }), encoding="utf-8")
        app.state.library_dirs.add(out)
        app.state.library_db.sync_dirs([out])
        resp = client.patch("/transcripts/loc1/relabel",
                            json={"SPEAKER_00": "Bob"})
        assert resp.status_code == 200, resp.text
        # Local relabel rewrote the file in place (relabel() applies the
        # mapping into speakers); no _clocks needed.
        doc = json.loads(local.read_text())
        assert doc["speakers"]["SPEAKER_00"] == "Bob"
        assert "_clocks" not in doc
    finally:
        routes_client._TEST_TRANSPORT = None
