from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from speechtotext.api.app import create_app
from speechtotext.api.routes_ingest import sweep_partial_uploads
from tests.api._signing import signed_headers


def _register_device(app) -> tuple[SigningKey, str]:
    sk = SigningKey.generate()
    device_id = "dev-import-test"
    app.state.device_registry.register(
        device_id=device_id,
        pubkey_b64=base64.b64encode(bytes(sk.verify_key)).decode("ascii"),
        name="ESP32 recorder",
    )
    return sk, device_id


def _make_app(tmp_path: Path):
    app = create_app(
        library_db_path=tmp_path / "library.db",
        devices_db_path=tmp_path / "devices.db",
    )
    # create_app defaults incoming_dir to the real app-data dir; pin it to
    # tmp_path so staged/committed files don't leak into (or get polluted
    # by) the real directory across test runs.
    app.state.incoming_dir = tmp_path / "incoming"
    return app


def _stage_audio(client: TestClient, sk, device_id: str, body: bytes = b"RIFF...") -> str:
    path = "/transcripts/import/audio?filename=a.flac"
    response = client.post(
        path,
        content=body,
        headers={
            "Content-Type": "audio/flac",
            **signed_headers(sk, device_id, "POST", path, body),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["audio_ref"]


def _admin_client(app, monkeypatch) -> TestClient:
    monkeypatch.setenv("LOCALLEXIS_API_TOKEN", "secret")
    return TestClient(app)


def _post_import(client: TestClient, body: dict):
    return client.post(
        "/transcripts/import",
        json=body,
        headers={"Authorization": "Bearer secret"},
    )


def test_import_audio_stages_file(tmp_path: Path, monkeypatch) -> None:
    app = create_app(
        library_db_path=tmp_path / "library.db",
        devices_db_path=tmp_path / "devices.db",
    )
    # create_app defaults incoming_dir to the real app-data dir; pin it to
    # tmp_path so staged files don't leak into (or get polluted by) the
    # real directory across test runs.
    app.state.incoming_dir = tmp_path / "incoming"
    fake_run = MagicMock()
    monkeypatch.setattr("speechtotext.api.runner.run_transcribe_job", fake_run)
    sk, device_id = _register_device(app)
    client = TestClient(app)

    body = b"RIFF\x24\x00\x00\x00WAVEfmt "
    path = "/transcripts/import/audio?filename=a.flac"
    response = client.post(
        path,
        content=body,
        headers={
            "Content-Type": "audio/flac",
            **signed_headers(sk, device_id, "POST", path, body),
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["audio_ref"].endswith(".import")
    assert payload["bytes_received"] == len(body)

    incoming = Path(app.state.incoming_dir)
    staged = incoming / payload["audio_ref"]
    assert staged.read_bytes() == body

    assert app.state.jobs.all() == []
    fake_run.assert_not_called()


def test_import_audio_rejects_bad_signature(tmp_path: Path, monkeypatch) -> None:
    app = create_app(
        library_db_path=tmp_path / "library.db",
        devices_db_path=tmp_path / "devices.db",
    )
    app.state.incoming_dir = tmp_path / "incoming"
    fake_run = MagicMock()
    monkeypatch.setattr("speechtotext.api.runner.run_transcribe_job", fake_run)
    sk, device_id = _register_device(app)
    client = TestClient(app)

    body = b"RIFF\x24\x00\x00\x00WAVEfmt "
    tampered = body + b"tampered"
    path = "/transcripts/import/audio?filename=a.flac"
    response = client.post(
        path,
        content=tampered,
        headers={
            "Content-Type": "audio/flac",
            **signed_headers(sk, device_id, "POST", path, body),
        },
    )

    assert response.status_code == 401
    fake_run.assert_not_called()

    incoming = Path(app.state.incoming_dir)
    leftovers = list(incoming.glob("*.import")) + list(incoming.glob("*.partial"))
    assert leftovers == []


def test_stale_import_files_swept(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    stale = incoming / "stale.import"
    stale.write_bytes(b"old")
    fresh = incoming / "fresh.import"
    fresh.write_bytes(b"new")

    old_time = time.time() - 25 * 3600
    os.utime(stale, (old_time, old_time))

    removed = sweep_partial_uploads(incoming)

    assert removed >= 1
    assert not stale.exists()
    assert fresh.exists()


# ── Commit step: POST /transcripts/import ──────────────────────────────────


def _base_doc(**extra) -> dict:
    doc = {
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "spk_0", "text": "hello world"}],
        "speakers": {"spk_0": "Alice"},
    }
    doc.update(extra)
    return doc


def test_import_commit_writes_and_indexes(tmp_path: Path, monkeypatch) -> None:
    app = _make_app(tmp_path)
    sk, device_id = _register_device(app)
    client = TestClient(app)
    ref = _stage_audio(client, sk, device_id)

    admin = _admin_client(app, monkeypatch)
    doc = _base_doc(_history=[{"op": "x"}], custom_x=1)
    response = _post_import(
        admin,
        {
            "tid": "alpha",
            "transcript": doc,
            "audio_ref": ref,
            "audio_filename": "a.flac",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"imported": True}

    incoming = Path(app.state.incoming_dir)
    json_path = incoming / "alpha.json"
    assert json_path.exists()
    stored = json.loads(json_path.read_text(encoding="utf-8"))

    audio_path = Path(stored["audio_path"])
    assert audio_path.is_file()
    assert audio_path.name.endswith("a.flac")

    txt_path = incoming / "alpha.txt"
    assert txt_path.exists()
    assert "hello world" in txt_path.read_text(encoding="utf-8")

    db = app.state.library_db
    assert db.get_path("alpha") is not None
    count = db._conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE transcript_id='alpha'"
    ).fetchone()[0]
    assert count > 0

    # unknown fields survive untouched
    assert stored["_history"] == [{"op": "x"}]
    assert stored["custom_x"] == 1


def test_import_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    app = _make_app(tmp_path)
    sk, device_id = _register_device(app)
    client = TestClient(app)
    ref = _stage_audio(client, sk, device_id)

    admin = _admin_client(app, monkeypatch)
    doc = _base_doc()
    body = {
        "tid": "alpha",
        "transcript": doc,
        "audio_ref": ref,
        "audio_filename": "a.flac",
    }
    first = _post_import(admin, body)
    assert first.status_code == 200, first.text
    assert first.json() == {"imported": True}

    json_path = Path(app.state.incoming_dir) / "alpha.json"
    mtime_before = json_path.stat().st_mtime_ns

    second = _post_import(
        admin,
        {"tid": "alpha", "transcript": doc, "audio_ref": None, "audio_filename": None},
    )
    assert second.status_code == 200, second.text
    assert second.json() == {"imported": False, "reason": "exists"}
    assert json_path.stat().st_mtime_ns == mtime_before


def test_import_without_audio(tmp_path: Path, monkeypatch) -> None:
    app = _make_app(tmp_path)
    admin = _admin_client(app, monkeypatch)
    doc = _base_doc(audio_path="whatever-the-client-said.wav")

    response = _post_import(
        admin,
        {"tid": "beta", "transcript": doc, "audio_ref": None, "audio_filename": None},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"imported": True}

    # audio_path is hub-controlled; without staged audio it must be ABSENT
    # (a laptop-local path is meaningless — and dangerous — on the hub).
    json_path = Path(app.state.incoming_dir) / "beta.json"
    stored = json.loads(json_path.read_text(encoding="utf-8"))
    assert "audio_path" not in stored


def test_import_strips_attacker_audio_path(tmp_path: Path, monkeypatch) -> None:
    """Regression: a client-supplied audio_path must never reach the stored
    doc — GET /transcripts/{tid}/audio serves it verbatim, so an arbitrary
    path would disclose any hub-readable file."""
    secret = tmp_path / "secret.txt"
    secret.write_text("hunter2", encoding="utf-8")

    app = _make_app(tmp_path)
    admin = _admin_client(app, monkeypatch)
    doc = _base_doc(audio_path=str(secret))

    response = _post_import(
        admin,
        {"tid": "leak", "transcript": doc, "audio_ref": None, "audio_filename": None},
    )
    assert response.status_code == 200, response.text

    stored = json.loads(
        (Path(app.state.incoming_dir) / "leak.json").read_text(encoding="utf-8")
    )
    assert "audio_path" not in stored


def test_import_exists_on_disk_but_not_indexed(tmp_path: Path, monkeypatch) -> None:
    """TOCTOU guard: an on-disk json the DB doesn't know about (post-restart,
    mid-rebuild) must still count as "exists" and never be overwritten."""
    app = _make_app(tmp_path)
    incoming = Path(app.state.incoming_dir)
    incoming.mkdir(parents=True, exist_ok=True)
    victim = incoming / "victim.json"
    original = '{"segments": [], "note": "pre-existing, unindexed"}'
    victim.write_text(original, encoding="utf-8")
    assert app.state.library_db.get_path("victim") is None  # really unindexed

    admin = _admin_client(app, monkeypatch)
    response = _post_import(
        admin,
        {
            "tid": "victim",
            "transcript": _base_doc(),
            "audio_ref": None,
            "audio_filename": None,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"imported": False, "reason": "exists"}
    assert victim.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    "doc",
    [
        {"segments": "not a list"},
        {"segments": ["not", "dicts"]},
        {"speakers": ["not", "a", "dict"]},
    ],
)
def test_import_rejects_bad_shape(tmp_path: Path, monkeypatch, doc: dict) -> None:
    app = _make_app(tmp_path)
    admin = _admin_client(app, monkeypatch)

    response = _post_import(
        admin,
        {"tid": "shapey", "transcript": doc, "audio_ref": None, "audio_filename": None},
    )
    assert response.status_code == 400, response.text
    assert not (Path(app.state.incoming_dir) / "shapey.json").exists()


def test_import_rejects_oversized_body(tmp_path: Path, monkeypatch) -> None:
    app = _make_app(tmp_path)
    app.state.max_upload_bytes = 64
    admin = _admin_client(app, monkeypatch)
    doc = _base_doc(padding="x" * 500)

    response = _post_import(
        admin,
        {"tid": "big", "transcript": doc, "audio_ref": None, "audio_filename": None},
    )
    assert response.status_code == 413, response.text
    assert not (Path(app.state.incoming_dir) / "big.json").exists()


@pytest.mark.parametrize(
    "audio_ref",
    ["..%2Fx.import", "a/b.import", "nonexistent.import", "a.import.no-suffix"],
)
def test_import_rejects_bad_refs(tmp_path: Path, monkeypatch, audio_ref: str) -> None:
    app = _make_app(tmp_path)
    Path(app.state.incoming_dir).mkdir(parents=True, exist_ok=True)
    admin = _admin_client(app, monkeypatch)
    doc = _base_doc()

    response = _post_import(
        admin,
        {
            "tid": "gamma",
            "transcript": doc,
            "audio_ref": audio_ref,
            "audio_filename": "a.flac",
        },
    )
    assert response.status_code == 400, response.text


def test_import_rejects_bad_tid(tmp_path: Path, monkeypatch) -> None:
    app = _make_app(tmp_path)
    admin = _admin_client(app, monkeypatch)
    doc = _base_doc()

    response = _post_import(
        admin,
        {"tid": "../evil", "transcript": doc, "audio_ref": None, "audio_filename": None},
    )
    assert response.status_code == 400, response.text
