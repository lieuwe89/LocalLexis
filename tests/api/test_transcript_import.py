from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from unittest.mock import MagicMock

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
