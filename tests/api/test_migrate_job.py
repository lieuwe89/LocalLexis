"""Tests for POST /client/hub/migrate: sweep_local as a job, migrated_at
flag, and the new client-state fields surfaced on GET /client/hub."""
import base64
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app
from speechtotext.client import migrate


@pytest.fixture()
def hub(tmp_path, monkeypatch):
    from speechtotext.api import routes_client, runner

    app = create_app(library_db_path=tmp_path / "hub-lib.db")
    client = TestClient(app)
    routes_client._TEST_TRANSPORT = httpx.ASGITransport(app=app)

    def fake_run_transcribe_job(registry, job_id, audio_path, **kw):
        pass
    monkeypatch.setattr(runner, "run_transcribe_job", fake_run_transcribe_job)

    yield app, client
    routes_client._TEST_TRANSPORT = None


def _pair_laptop(hub_client_testclient, ws="ws-migrate-job"):
    from speechtotext.api import routes_client
    from speechtotext.client import join

    tok = hub_client_testclient.post("/pair/tokens").json()["token"]
    pairing = base64.b64encode(json.dumps({
        "hub_url": str(hub_client_testclient.base_url),
        "workspace_id": ws,
        "token": tok,
    }).encode()).decode()
    return join.join_hub(
        pairing, device_name="e2e-laptop",
        transport=routes_client.sync_test_transport(),
    )


def _write_local_transcript(tmp_path, db, tid):
    """A local original: json + audio sidecar, indexed origin='local'."""
    local_dir = tmp_path / "local"
    local_dir.mkdir(exist_ok=True)
    audio = local_dir / f"{tid}.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 64)
    json_path = local_dir / f"{tid}.json"
    json_path.write_text(json.dumps({
        "audio_path": str(audio),
        "segments": [{"speaker": "SPEAKER_00", "text": "hoi wereld"}],
        "speakers": {"SPEAKER_00": "SPEAKER_00"},
    }), encoding="utf-8")
    db.upsert_path(json_path)
    return json_path, audio


def _laptop_library_db(tmp_path):
    from speechtotext.api.library_db import LibraryDB
    from speechtotext.client.paths import synced_dir

    return LibraryDB(tmp_path / "laptop-lib.db", hub_synced_dir=synced_dir())


def _poll_terminal(client, job_id, timeout=5.0):
    from speechtotext.api.jobs import JobStatus

    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in (JobStatus.complete.value, JobStatus.failed.value):
            return job
        time.sleep(0.02)
    raise TimeoutError(f"job {job_id} did not reach a terminal state: {job}")


def test_migrate_job_reports_and_sets_migrated_at(hub, tmp_path):
    hub_app, hub_client = hub
    _pair_laptop(hub_client)
    db = _laptop_library_db(tmp_path)
    p1, a1 = _write_local_transcript(tmp_path, db, "meeting-a")
    p2, a2 = _write_local_transcript(tmp_path, db, "meeting-b")

    # The migrate job sweeps request.app.state.library_db; swap in our
    # laptop db (loopback: this app is both hub and client under test).
    hub_app.state.library_db = db

    resp = hub_client.post("/client/hub/migrate")
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]

    job = _poll_terminal(hub_client, job_id)
    assert job["status"] == "complete", job

    from speechtotext.client import state as state_module
    st = state_module.load()
    assert isinstance(st.migrated_at, float)

    assert not p1.exists()
    assert not p2.exists()
    db.close()


def test_migrate_job_partial_failure_keeps_flag_unset(hub, tmp_path, monkeypatch):
    hub_app, hub_client = hub
    _pair_laptop(hub_client, ws="ws-migrate-partial")
    db = _laptop_library_db(tmp_path)
    _write_local_transcript(tmp_path, db, "meeting-c")
    hub_app.state.library_db = db

    from speechtotext.client import migrate as migrate_mod

    def fake_sweep_local(client, db_arg, *, limit=10000):
        return {"migrated": [], "failed": [{"id": "meeting-c", "error": "boom"}]}
    monkeypatch.setattr(migrate_mod, "sweep_local", fake_sweep_local)

    hub_app.state.library_db = db
    resp = hub_client.post("/client/hub/migrate")
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]

    job = _poll_terminal(hub_client, job_id)
    assert job["status"] == "complete", job

    from speechtotext.client import state as state_module
    st = state_module.load()
    assert st.migrated_at is None
    db.close()


def test_migrate_endpoint_409_when_not_joined(tmp_path):
    app = create_app(library_db_path=tmp_path / "lib.db")
    client = TestClient(app)
    resp = client.post("/client/hub/migrate")
    assert resp.status_code == 409


def test_migrate_in_flight_guard(hub, tmp_path, monkeypatch):
    """A second POST while a migrate job is pending/running -> 409; after
    the job reaches a terminal state a new POST is accepted again."""
    from speechtotext.api import runner
    from speechtotext.api.jobs import JobStatus

    hub_app, hub_client = hub
    _pair_laptop(hub_client, ws="ws-guard")

    # No-op runner: the job record stays pending (i.e. "in flight").
    monkeypatch.setattr(runner, "run_migrate_job", lambda registry, job_id, db: None)

    r1 = hub_client.post("/client/hub/migrate")
    assert r1.status_code == 202, r1.text
    job_id = r1.json()["job_id"]

    r2 = hub_client.post("/client/hub/migrate")
    assert r2.status_code == 409
    assert "already running" in r2.json()["detail"]

    hub_app.state.jobs.get(job_id).status = JobStatus.complete
    r3 = hub_client.post("/client/hub/migrate")
    assert r3.status_code == 202, r3.text


def test_hub_status_exposes_new_fields(hub, tmp_path):
    hub_app, hub_client = hub
    _pair_laptop(hub_client, ws="ws-status-fields")

    status = hub_client.get("/client/hub").json()
    assert status["joined"] is True
    assert "migrated_at" in status
    assert status["migrated_at"] is None
    assert status["offline_capture"] == "local"
