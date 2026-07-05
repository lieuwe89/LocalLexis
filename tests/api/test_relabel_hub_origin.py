import base64
import json

from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


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
