import base64
import hashlib

import httpx
from nacl.signing import SigningKey

from speechtotext.api.auth import build_signed_message
from speechtotext.client.hub_client import HubClient, signed_headers


def test_signed_headers_verify_against_canonical_message():
    sk = SigningKey.generate()
    body = b'{"x":1}'
    headers = signed_headers(sk, "dev-1", "PATCH", "/transcripts/t1", body)
    msg = build_signed_message(
        "PATCH", "/transcripts/t1", "",
        headers["X-Timestamp"], headers["X-Nonce"],
        hashlib.sha256(body).digest(),
    )
    sig = base64.b64decode(headers["X-Signature-B64"])
    sk.verify_key.verify(msg, sig)  # raises BadSignatureError on mismatch


def test_signed_headers_include_query_in_target():
    sk = SigningKey.generate()
    headers = signed_headers(
        sk, "dev-1", "POST", "/jobs/upload?filename=a.wav", b"AUDIO"
    )
    msg = build_signed_message(
        "POST", "/jobs/upload", "filename=a.wav",
        headers["X-Timestamp"], headers["X-Nonce"],
        hashlib.sha256(b"AUDIO").digest(),
    )
    sk.verify_key.verify(msg, base64.b64decode(headers["X-Signature-B64"]))


def _echo_transport():
    """httpx MockTransport that echoes method/path/headers back as JSON."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "method": request.method,
            "path": request.url.path,
            "query": request.url.query.decode(),
            "device": request.headers.get("X-Device-Id"),
            "has_sig": "X-Signature-B64" in request.headers,
            "body_len": len(request.read()),
        })
    return httpx.MockTransport(handler)


def test_client_get_sync_since_signs_request():
    sk = SigningKey.generate()
    client = HubClient(
        "http://hub:8010", "dev-1", sk, transport=_echo_transport()
    )
    out = client.get_json("/sync/since/0.0")
    assert out["device"] == "dev-1"
    assert out["has_sig"] is True
    assert out["path"] == "/sync/since/0.0"


def test_client_upload_streams_file(tmp_path):
    audio = tmp_path / "rec.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 100)
    sk = SigningKey.generate()
    client = HubClient(
        "http://hub:8010", "dev-1", sk, transport=_echo_transport()
    )
    out = client.upload_audio(audio)
    assert out["path"] == "/jobs/upload"
    assert out["query"] == "filename=rec.wav"
    assert out["body_len"] == 104
