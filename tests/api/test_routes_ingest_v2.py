"""Streaming /jobs/upload scenarios: oversize mid-stream, bad signature
post-stream, replay nonce post-stream, orphan .partial sweep at startup."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from speechtotext.api.app import create_app
from speechtotext.api.routes_ingest import sweep_partial_uploads
from tests.api._signing import signed_headers


def _register_device(app) -> tuple[SigningKey, str]:
    sk = SigningKey.generate()
    device_id = "dev-stream"
    app.state.device_registry.register(
        device_id=device_id,
        pubkey_b64=base64.b64encode(bytes(sk.verify_key)).decode("ascii"),
        name="ESP32",
    )
    return sk, device_id


def _make_app(tmp_path, monkeypatch):
    app = create_app(
        library_db_path=tmp_path / "library.db",
        devices_db_path=tmp_path / "devices.db",
    )
    monkeypatch.setattr(
        "speechtotext.api.runner.run_transcribe_job", MagicMock()
    )
    return app


def test_signature_failure_deletes_partial(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    sk, device_id = _register_device(app)
    client = TestClient(app)
    path = "/jobs/upload?filename=sig-fails.wav"
    body = b"RIFF\x24\x00\x00\x00WAVEfmt "

    headers = signed_headers(sk, device_id, "POST", path, body)
    headers["X-Signature-B64"] = base64.b64encode(b"\x00" * 64).decode()

    r = client.post(path, content=body, headers=headers)
    assert r.status_code == 401

    incoming = Path(app.state.incoming_dir)
    leftovers = list(incoming.glob("*.partial")) if incoming.exists() else []
    assert leftovers == []
    audio = list(incoming.glob("*sig-fails.wav")) if incoming.exists() else []
    assert audio == []


def test_replay_nonce_deletes_partial(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    sk, device_id = _register_device(app)
    client = TestClient(app)
    path = "/jobs/upload?filename=replay.wav"
    body = b"audio"

    first = signed_headers(
        sk, device_id, "POST", path, body, nonce="fixed-nonce-1"
    )
    r1 = client.post(path, content=body, headers=first)
    assert r1.status_code == 202, r1.text

    second = signed_headers(
        sk, device_id, "POST", path, body, nonce="fixed-nonce-1"
    )
    r2 = client.post(path, content=body, headers=second)
    assert r2.status_code == 401
    assert "replay" in r2.json()["detail"]

    incoming = Path(app.state.incoming_dir)
    leftovers = list(incoming.glob("*.partial"))
    assert leftovers == []


def test_oversize_via_content_length_rejects_pre_stream(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app.state.max_upload_bytes = 4
    sk, device_id = _register_device(app)
    client = TestClient(app)
    path = "/jobs/upload?filename=big.wav"
    body = b"too long for limit"

    r = client.post(
        path, content=body, headers=signed_headers(sk, device_id, "POST", path, body)
    )
    assert r.status_code == 413

    incoming = Path(app.state.incoming_dir)
    leftovers = list(incoming.glob("*.partial")) if incoming.exists() else []
    assert leftovers == []


def test_sweep_partial_uploads_removes_orphans(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "abc.partial").write_bytes(b"x")
    (incoming / "def.partial").write_bytes(b"y")
    (incoming / "keep.wav").write_bytes(b"z")

    removed = sweep_partial_uploads(incoming)

    assert removed == 2
    assert (incoming / "keep.wav").exists()
    assert not any(incoming.glob("*.partial"))


def test_sweep_partial_uploads_handles_missing_dir(tmp_path):
    removed = sweep_partial_uploads(tmp_path / "does-not-exist")
    assert removed == 0
