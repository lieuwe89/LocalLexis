import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


@pytest.fixture()
def hub(tmp_path, monkeypatch):
    """A real hub app + TestClient, with the sync test transport installed
    so the client library's sync HTTP loops back into it. Transcription is
    stubbed so no ML models load."""
    from speechtotext.api import routes_client, runner

    app = create_app(library_db_path=tmp_path / "hub-lib.db")
    client = TestClient(app)
    routes_client._TEST_TRANSPORT = httpx.ASGITransport(app=app)

    received = []
    def fake_run_transcribe_job(registry, job_id, audio_path, **kw):
        received.append(audio_path)
    monkeypatch.setattr(runner, "run_transcribe_job", fake_run_transcribe_job)

    yield app, client, received
    routes_client._TEST_TRANSPORT = None


def _pair_laptop(hub_client_testclient):
    """Pair the 'laptop' (client library) against the hub. Returns the
    joined ClientState."""
    from speechtotext.api import routes_client
    from speechtotext.client import join

    tok = hub_client_testclient.post("/pair/tokens").json()["token"]
    pairing = base64.b64encode(json.dumps({
        "hub_url": str(hub_client_testclient.base_url),
        "workspace_id": "ws-e2e",
        "token": tok,
    }).encode()).decode()
    return join.join_hub(
        pairing, device_name="e2e-laptop",
        transport=routes_client.sync_test_transport(),
    )


def _laptop_hub_client():
    from speechtotext.api import routes_client
    from speechtotext.client import identity, state
    from speechtotext.client.hub_client import HubClient

    st = state.load()
    ident = identity.load()
    return HubClient(
        st.hub_url, st.device_id, ident.signing_key(),
        transport=routes_client.sync_test_transport(),
    )


def test_pair_upload_sync_roundtrip(hub, tmp_path):
    from speechtotext.client import state, sync_puller, upload_queue
    from speechtotext.client.paths import synced_dir

    hub_app, hub_client, received = hub

    # 1. Pair the laptop with the hub.
    st = _pair_laptop(hub_client)
    assert st.device_id.startswith("dev-")
    assert state.load() is not None  # laptop is joined

    # 2. Enqueue an audio file to the outbox and sweep it to the hub.
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 256)
    upload_queue.enqueue(audio, job_id="local-1")
    sent = upload_queue.sweep(_laptop_hub_client())
    assert len(sent) == 1
    assert received, "hub should have dispatched (stubbed) transcription"
    assert upload_queue.pending() == []  # outbox drained

    # 3. Hub 'finishes' transcription: write a transcript into a hub
    #    library dir and index it (origin stays local on the HUB side).
    out = tmp_path / "hub-out"
    out.mkdir()
    (out / "meeting.json").write_text(json.dumps({
        "audio_path": received[0] if isinstance(received[0], str) else str(received[0]),
        "segments": [{"speaker": "SPEAKER_00", "text": "hoi wereld"}],
        "speakers": {"SPEAKER_00": "SPEAKER_00"},
    }), encoding="utf-8")
    hub_app.state.library_dirs.add(out)
    hub_app.state.library_db.sync_dirs([out])

    # 4. Laptop pulls sync -> transcript lands in the laptop's synced dir.
    written = sync_puller.pull_once(_laptop_hub_client())
    assert [p.name for p in written] == ["meeting.json"]
    assert (synced_dir() / "meeting.json").exists()

    # 5. It is searchable on the laptop, tagged origin='hub'.
    from speechtotext.api.library_db import LibraryDB
    laptop_db = LibraryDB(tmp_path / "laptop-lib.db", hub_synced_dir=synced_dir())
    laptop_db.sync_dirs([synced_dir()])
    hits = laptop_db.search("wereld")
    assert hits, "synced transcript should be searchable on the laptop"
    assert hits[0]["origin"] == "hub"
    laptop_db.close()


def test_upload_signature_rejected_after_unpair(hub, tmp_path):
    """After the hub unpairs the device, its signed uploads are refused —
    proves the signature path is real, not bypassed."""
    from speechtotext.client import upload_queue

    hub_app, hub_client, received = hub
    _pair_laptop(hub_client)

    # Unpair on the hub side: delete the device from the registry.
    from speechtotext.client import state
    device_id = state.load().device_id
    hub_app.state.device_registry.delete(device_id)

    audio = tmp_path / "x.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 32)
    upload_queue.enqueue(audio, job_id="j1")
    # sweep swallows the upload error and keeps the entry (hub 401).
    sent = upload_queue.sweep(_laptop_hub_client())
    assert sent == []
    assert len(upload_queue.pending()) == 1
