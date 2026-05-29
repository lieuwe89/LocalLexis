from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from speechtotext.api.app import create_app
from tests.api._signing import signed_headers


def _register_device(app) -> tuple[SigningKey, str]:
    sk = SigningKey.generate()
    device_id = "dev-upload-test"
    app.state.device_registry.register(
        device_id=device_id,
        pubkey_b64=base64.b64encode(bytes(sk.verify_key)).decode("ascii"),
        name="ESP32 recorder",
    )
    return sk, device_id


def test_signed_whole_file_upload_stores_audio_and_dispatches_job(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LOCALLEXIS_API_TOKEN", "hub-admin-token")
    app = create_app(
        library_db_path=tmp_path / "library.db",
        devices_db_path=tmp_path / "devices.db",
    )
    fake_run = MagicMock()
    monkeypatch.setattr("speechtotext.api.runner.run_transcribe_job", fake_run)
    sk, device_id = _register_device(app)
    client = TestClient(app)

    body = b"RIFF\x24\x00\x00\x00WAVEfmt "
    path = "/jobs/upload?filename=field-note.wav"
    response = client.post(
        path,
        content=body,
        headers={
            "Content-Type": "audio/wav",
            **signed_headers(sk, device_id, "POST", path, body),
        },
    )

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["job_id"]
    assert payload["bytes_received"] == len(body)
    assert "audio_path" not in payload

    audio_path = Path(app.state.jobs.get(payload["job_id"]).audio_path)
    assert audio_path.name.endswith("-field-note.wav")
    assert audio_path.read_bytes() == body
    assert audio_path.parent.name == "incoming"

    fake_run.assert_called_once()
    args, kwargs = fake_run.call_args
    assert args[0] is app.state.jobs
    assert args[1] == payload["job_id"]
    assert args[2] == audio_path
    assert kwargs == {}


def test_upload_cleans_saved_audio_when_dispatch_fails(
    tmp_path: Path, monkeypatch
) -> None:
    app = create_app(
        library_db_path=tmp_path / "library.db",
        devices_db_path=tmp_path / "devices.db",
    )
    fake_run = MagicMock(side_effect=RuntimeError("queue unavailable"))
    monkeypatch.setattr("speechtotext.api.runner.run_transcribe_job", fake_run)
    sk, device_id = _register_device(app)
    client = TestClient(app)
    path = "/jobs/upload?filename=dispatch-fails.wav"
    body = b"RIFF\x24\x00\x00\x00WAVEfmt "

    response = client.post(
        path,
        content=body,
        headers=signed_headers(sk, device_id, "POST", path, body),
    )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "failed to dispatch upload job: RuntimeError: queue unavailable"
    )
    incoming = Path(app.state.incoming_dir)
    assert list(incoming.glob("*")) == []


def test_upload_rejects_empty_body(tmp_path: Path, monkeypatch) -> None:
    app = create_app(
        library_db_path=tmp_path / "library.db",
        devices_db_path=tmp_path / "devices.db",
    )
    fake_run = MagicMock()
    monkeypatch.setattr("speechtotext.api.runner.run_transcribe_job", fake_run)
    sk, device_id = _register_device(app)
    client = TestClient(app)
    path = "/jobs/upload?filename=empty.wav"

    response = client.post(
        path,
        content=b"",
        headers=signed_headers(sk, device_id, "POST", path, b""),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "audio upload body cannot be empty"
    fake_run.assert_not_called()


def test_upload_rejects_body_over_configured_limit(
    tmp_path: Path, monkeypatch
) -> None:
    app = create_app(
        library_db_path=tmp_path / "library.db",
        devices_db_path=tmp_path / "devices.db",
    )
    app.state.max_upload_bytes = 4
    fake_run = MagicMock()
    monkeypatch.setattr("speechtotext.api.runner.run_transcribe_job", fake_run)
    sk, device_id = _register_device(app)
    client = TestClient(app)
    path = "/jobs/upload?filename=too-big.wav"
    body = b"audio"

    response = client.post(
        path,
        content=body,
        headers=signed_headers(sk, device_id, "POST", path, body),
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "audio upload exceeds 4 byte limit"
    fake_run.assert_not_called()


def test_upload_rejects_non_basename_filename(tmp_path: Path) -> None:
    app = create_app(
        library_db_path=tmp_path / "library.db",
        devices_db_path=tmp_path / "devices.db",
    )
    sk, device_id = _register_device(app)
    client = TestClient(app)
    path = "/jobs/upload?filename=../outside.wav"
    body = b"audio"

    response = client.post(
        path,
        content=body,
        headers=signed_headers(sk, device_id, "POST", path, body),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "filename must be a simple basename"
