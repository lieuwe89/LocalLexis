import base64
import hashlib
import json

import httpx
import pytest
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


def test_client_patch_json_signs_and_sends_json():
    sk = SigningKey.generate()
    client = HubClient(
        "http://hub:8010", "dev-1", sk, transport=_echo_transport()
    )
    out = client.patch_json("/transcripts/t1", {"op": "relabel"})
    assert out["method"] == "PATCH"
    assert out["path"] == "/transcripts/t1"
    assert out["device"] == "dev-1"
    assert out["has_sig"] is True
    assert out["body_len"] == len(b'{"op": "relabel"}')


def test_client_raises_on_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "unknown device"})

    sk = SigningKey.generate()
    client = HubClient(
        "http://hub:8010", "dev-1", sk,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(httpx.HTTPStatusError):
        client.get_json("/sync/since/0.0")


def test_stream_get_signs_and_streams():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-Device-Id") == "dev-1"
        assert "X-Signature-B64" in request.headers
        assert "X-Timestamp" in request.headers
        assert "X-Nonce" in request.headers
        assert request.headers.get("Range") == "bytes=0-3"
        return httpx.Response(
            200,
            content=b"audio-bytes",
            headers={
                "Content-Type": "audio/wav",
                "Accept-Ranges": "bytes",
            },
        )

    sk = SigningKey.generate()
    client = HubClient(
        "http://hub:8010", "dev-1", sk, transport=httpx.MockTransport(handler)
    )
    resp = client.stream_get(
        "/audio/abc", extra_headers={"Range": "bytes=0-3"}
    )
    assert b"".join(resp.iter_bytes()) == b"audio-bytes"
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.headers["accept-ranges"] == "bytes"
    resp.close()


def test_stream_get_does_not_raise_on_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "not found"})

    sk = SigningKey.generate()
    client = HubClient(
        "http://hub:8010", "dev-1", sk, transport=httpx.MockTransport(handler)
    )
    resp = client.stream_get("/audio/missing")
    assert resp.status_code == 404
    resp.close()


def test_upload_filename_with_space_is_percent_encoded(tmp_path):
    audio = tmp_path / "my rec.wav"
    audio.write_bytes(b"RIFF00")
    sk = SigningKey.generate()
    client = HubClient(
        "http://hub:8010", "dev-1", sk, transport=_echo_transport()
    )
    out = client.upload_audio(audio)
    assert out["query"] == "filename=my%20rec.wav"


def test_post_json_signs_and_posts():
    sk = SigningKey.generate()
    client = HubClient(
        "http://hub:8010", "dev-1", sk, transport=_echo_transport()
    )
    out = client.post_json("/transcripts/import", {"tid": "t1"})
    assert out["method"] == "POST"
    assert out["path"] == "/transcripts/import"
    assert out["device"] == "dev-1"
    assert out["has_sig"] is True
    assert out["body_len"] == len(b'{"tid": "t1"}')


def _import_transport(recorder):
    """Answers the two import-flow requests and records what it saw."""
    def handler(request: httpx.Request) -> httpx.Response:
        recorder.append(request)
        if request.url.path == "/transcripts/import/audio":
            return httpx.Response(200, json={"audio_ref": "r.import"})
        assert request.url.path == "/transcripts/import"
        return httpx.Response(200, json={"imported": True})
    return httpx.MockTransport(handler)


def test_import_transcript_two_step(tmp_path):
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 64)
    doc = {"segments": [{"speaker": "SPEAKER_00", "text": "hi"}]}
    json_path = tmp_path / "meeting.json"
    json_path.write_text(json.dumps(doc), encoding="utf-8")

    sk = SigningKey.generate()
    seen = []
    client = HubClient(
        "http://hub:8010", "dev-1", sk, transport=_import_transport(seen)
    )
    out = client.import_transcript(json_path, audio)

    assert out == {"imported": True}
    assert len(seen) == 2

    upload_req = seen[0]
    assert upload_req.url.path == "/transcripts/import/audio"
    assert upload_req.url.query.decode() == "filename=meeting.wav"
    assert upload_req.headers["Content-Type"] == "application/octet-stream"
    assert upload_req.headers["Content-Length"] == str(audio.stat().st_size)
    assert len(upload_req.read()) == audio.stat().st_size

    commit_req = seen[1]
    assert commit_req.url.path == "/transcripts/import"
    body = json.loads(commit_req.read())
    assert body["tid"] == "meeting"
    assert body["transcript"] == doc
    assert body["audio_ref"] == "r.import"
    assert body["audio_filename"] == "meeting.wav"


def test_import_transcript_json_only(tmp_path):
    doc = {"segments": []}
    json_path = tmp_path / "meeting.json"
    json_path.write_text(json.dumps(doc), encoding="utf-8")

    sk = SigningKey.generate()
    seen = []
    client = HubClient(
        "http://hub:8010", "dev-1", sk, transport=_import_transport(seen)
    )
    out = client.import_transcript(json_path, None)

    assert out == {"imported": True}
    assert len(seen) == 1
    body = json.loads(seen[0].read())
    assert body["tid"] == "meeting"
    assert body["audio_ref"] is None
    assert body["audio_filename"] is None


def test_import_transcript_missing_audio_file_falls_back_to_json_only(tmp_path):
    """audio_path is set but the file doesn't exist on disk (e.g. already
    cleaned up) -> behaves like the json-only case rather than crashing."""
    doc = {"segments": []}
    json_path = tmp_path / "meeting.json"
    json_path.write_text(json.dumps(doc), encoding="utf-8")
    missing_audio = tmp_path / "gone.wav"

    sk = SigningKey.generate()
    seen = []
    client = HubClient(
        "http://hub:8010", "dev-1", sk, transport=_import_transport(seen)
    )
    out = client.import_transcript(json_path, missing_audio)

    assert out == {"imported": True}
    assert len(seen) == 1
    body = json.loads(seen[0].read())
    assert body["audio_ref"] is None
    assert body["audio_filename"] is None
