"""Protocol v2: byte-exact golden-vector tests for build_signed_message
and end-to-end verify of a tampered body."""

from __future__ import annotations

import base64
import hashlib

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from speechtotext.api.app import create_app
from speechtotext.api.auth import build_signed_message
from tests.api._signing import signed_headers


GOLDEN_SEED = bytes(range(32))
GOLDEN_PUBKEY_B64 = "A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg="
GOLDEN_METHOD = "POST"
GOLDEN_TARGET = "/jobs/upload?filename=t.wav"
GOLDEN_PATH = "/jobs/upload"
GOLDEN_QUERY = "filename=t.wav"
GOLDEN_TS = "1700000000"
GOLDEN_NONCE = "abc123"
GOLDEN_BODY = b"hello"
GOLDEN_BODY_SHA256_HEX = (
    "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
)
GOLDEN_MSG_HEX = (
    "6c6f63616c6c657869732d7369672d76320a504f53540a2f6a6f62732f75706c"
    "6f61643f66696c656e616d653d742e7761760a313730303030303030300a6162"
    "633132330a2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e730433"
    "62938b9824"
)
GOLDEN_SIG_B64 = (
    "/OsfsMPLhgXoE+9izzKmxXq2JNcuGhUu6FbF23WnPYfqJQieQrYMTc8AbDa+g5j/"
    "WonMiJpvQpspFU8DbgpZAw=="
)


def test_build_signed_message_golden_vector_bytes():
    digest = hashlib.sha256(GOLDEN_BODY).digest()
    assert digest.hex() == GOLDEN_BODY_SHA256_HEX

    msg = build_signed_message(
        GOLDEN_METHOD,
        GOLDEN_PATH,
        GOLDEN_QUERY,
        GOLDEN_TS,
        GOLDEN_NONCE,
        digest,
    )
    assert msg.hex() == GOLDEN_MSG_HEX
    assert len(msg) == 101


def test_build_signed_message_golden_vector_signature():
    sk = SigningKey(GOLDEN_SEED)
    assert base64.b64encode(bytes(sk.verify_key)).decode() == GOLDEN_PUBKEY_B64

    digest = hashlib.sha256(GOLDEN_BODY).digest()
    msg = build_signed_message(
        GOLDEN_METHOD,
        GOLDEN_PATH,
        GOLDEN_QUERY,
        GOLDEN_TS,
        GOLDEN_NONCE,
        digest,
    )
    sig = sk.sign(msg).signature
    assert base64.b64encode(sig).decode() == GOLDEN_SIG_B64


def test_build_signed_message_empty_body_uses_well_known_digest():
    empty_digest = hashlib.sha256(b"").digest()
    assert (
        empty_digest.hex()
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    msg = build_signed_message("GET", "/sync/snapshot", "", "ts", "n", empty_digest)
    expected_prefix = b"locallexis-sig-v2\nGET\n/sync/snapshot\nts\nn\n"
    assert msg.startswith(expected_prefix)
    assert msg[len(expected_prefix):] == empty_digest


def test_build_signed_message_rejects_wrong_digest_length():
    with pytest.raises(ValueError, match="32 bytes"):
        build_signed_message("GET", "/", "", "ts", "n", b"too short")


def test_tampered_body_fails_verification(tmp_path, monkeypatch):
    """A captured request with the body altered must 401 on verify."""
    app = create_app(
        library_db_path=tmp_path / "library.db",
        devices_db_path=tmp_path / "devices.db",
    )
    monkeypatch.setattr(
        "speechtotext.api.runner.run_transcribe_job", lambda *a, **k: None
    )
    sk = SigningKey.generate()
    device_id = "dev-tamper"
    app.state.device_registry.register(
        device_id=device_id,
        pubkey_b64=base64.b64encode(bytes(sk.verify_key)).decode("ascii"),
        name="ESP32",
    )
    client = TestClient(app)
    path = "/jobs/upload?filename=ok.wav"
    body = b"RIFF\x24\x00\x00\x00WAVEfmt "

    headers = signed_headers(sk, device_id, "POST", path, body)
    tampered_body = body + b"\x00"  # one extra byte
    r = client.post(path, content=tampered_body, headers=headers)
    assert r.status_code == 401
    assert r.json()["detail"] == "signature verification failed"
