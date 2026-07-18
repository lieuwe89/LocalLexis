"""Loopback tests for speechtotext.client.migrate: push -> pull back ->
verify -> archive, against a real hub app (see test_hub_client_e2e.py for
the fixture conventions these copy)."""
import base64
import json

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


def _pair_laptop(hub_client_testclient):
    from speechtotext.api import routes_client
    from speechtotext.client import join

    tok = hub_client_testclient.post("/pair/tokens").json()["token"]
    pairing = base64.b64encode(json.dumps({
        "hub_url": str(hub_client_testclient.base_url),
        "workspace_id": "ws-migrate",
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


def _write_local_transcript(tmp_path, tid="meeting"):
    """A local original: json + audio sidecar, indexed origin='local'."""
    from speechtotext.api.library_db import LibraryDB
    from speechtotext.client.paths import synced_dir

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

    db = LibraryDB(tmp_path / "laptop-lib.db", hub_synced_dir=synced_dir())
    db.upsert_path(json_path)
    return db, json_path, audio


def test_migrate_one_full_cycle(hub, tmp_path):
    from speechtotext.client.paths import synced_dir

    hub_app, hub_client = hub
    _pair_laptop(hub_client)
    db, json_path, audio = _write_local_transcript(tmp_path)
    client = _laptop_hub_client()

    result = migrate.migrate_one(client, db, json_path)

    assert result == "migrated"
    assert hub_app.state.library_db.get_path("meeting") is not None
    assert (synced_dir() / "meeting.json").exists()

    row_path = db.get_path("meeting")
    assert row_path == synced_dir() / "meeting.json"

    assert not json_path.exists()
    trash_dir = json_path.parent / ".trash" / "meeting"
    assert (trash_dir / "meeting.json").exists()
    assert (trash_dir / "meeting.wav").exists()
    assert not audio.exists()
    db.close()


def test_migrate_one_verification_failure_keeps_original(hub, tmp_path, monkeypatch):
    from speechtotext.client import sync_puller
    from speechtotext.client.paths import synced_dir

    hub_app, hub_client = hub
    _pair_laptop(hub_client)
    db, json_path, audio = _write_local_transcript(tmp_path)
    client = _laptop_hub_client()

    def fake_pull_once(hub_client_arg):
        root = synced_dir()
        root.mkdir(parents=True, exist_ok=True)
        (root / "meeting.json").write_text(json.dumps({
            "segments": [],  # fewer segments than the original -> mismatch
            "speakers": {"SPEAKER_00": "SPEAKER_00"},
        }), encoding="utf-8")
        return [root / "meeting.json"]

    monkeypatch.setattr(sync_puller, "pull_once", fake_pull_once)

    with pytest.raises(migrate.MigrateError):
        migrate.migrate_one(client, db, json_path)

    assert json_path.exists()
    assert audio.exists()
    assert not (json_path.parent / ".trash").exists()
    db.close()


def test_migrate_one_stale_hub_copy_after_local_edit_fails_verify(hub, tmp_path):
    """Regression: interrupted run pushed v1, user then edits a segment TEXT
    locally (count + speakers unchanged). Re-push answers "exists" so the
    edit never reaches the hub; the pulled copy is stale. A count-only
    verify would archive the edited original — content equality must
    catch it."""
    hub_app, hub_client = hub
    _pair_laptop(hub_client)
    db, json_path, audio = _write_local_transcript(tmp_path)
    client = _laptop_hub_client()

    # Interrupted previous migration: push succeeded, archive never ran.
    client.import_transcript(json_path, audio)

    # Local edit afterwards: same segment count, same speakers, new text.
    doc = json.loads(json_path.read_text(encoding="utf-8"))
    doc["segments"][0]["text"] = "hoi bewerkte wereld"
    json_path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(migrate.MigrateError, match="segments mismatch"):
        migrate.migrate_one(client, db, json_path)

    assert json_path.exists()
    assert audio.exists()
    assert not (json_path.parent / ".trash").exists()
    db.close()


def test_migrate_one_trash_failure_still_returns_migrated(hub, tmp_path, monkeypatch):
    """If archiving fails after the verified hub copy is indexed, the bytes
    are safe on both sides — migrate_one logs loudly and still succeeds."""
    from speechtotext.client.paths import synced_dir

    hub_app, hub_client = hub
    _pair_laptop(hub_client)
    db, json_path, audio = _write_local_transcript(tmp_path)
    client = _laptop_hub_client()

    def broken_trash(path):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(migrate, "trash_transcript", broken_trash)

    assert migrate.migrate_one(client, db, json_path) == "migrated"
    assert json_path.exists()  # orphaned original, left in place
    assert db.get_path("meeting") == synced_dir() / "meeting.json"
    db.close()


def test_migrate_one_exists_on_hub_still_verifies_and_archives(hub, tmp_path):
    from speechtotext.client.paths import synced_dir

    hub_app, hub_client = hub
    _pair_laptop(hub_client)
    db, json_path, audio = _write_local_transcript(tmp_path)
    client = _laptop_hub_client()

    # Pre-import the same doc directly, simulating an interrupted previous
    # migration attempt that got as far as pushing but not archiving.
    first = client.import_transcript(json_path, audio)
    assert first["imported"] is True

    result = migrate.migrate_one(client, db, json_path)

    assert result == "migrated"
    assert hub_app.state.library_db.get_path("meeting") is not None
    assert (synced_dir() / "meeting.json").exists()
    assert not json_path.exists()
    assert (json_path.parent / ".trash" / "meeting" / "meeting.json").exists()
    db.close()
