import base64
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


# ── Signed-request helpers (block 5c) ──────────────────────────────────────
#
# PATCH /transcripts/{tid} requires a paired device signature. These
# helpers handle the pair + sign dance so each test stays concise. They
# also let us exercise the auth path realistically — no
# "auth_required=False" bypass — which is what production sees.


def _pair_device(client: TestClient, name: str = "test-device"):
    """Pair a fresh device. Returns (signing_key, device_id)."""
    from nacl.signing import SigningKey

    token = client.post("/pair/tokens").json()["token"]
    sk = SigningKey.generate()
    r = client.post(
        "/pair",
        json={
            "token": token,
            "device_pubkey_b64": base64.b64encode(
                bytes(sk.verify_key)
            ).decode("ascii"),
            "device_name": name,
        },
    )
    assert r.status_code == 200, r.text
    return sk, r.json()["device_id"]


def _signed_patch(
    client: TestClient, sk, device_id: str, path: str, body: dict
):
    """PATCH ``path`` with a body signed by ``sk`` as ``device_id``.

    Bypasses TestClient's json= serialization quirks by sending the
    body as raw bytes (``content=``) so the signed bytes are exactly
    the bytes the server reads back via ``await request.body()``.
    """
    body_bytes = json.dumps(body).encode("utf-8")
    msg = b"PATCH\n" + path.encode("ascii") + b"\n" + body_bytes
    sig = sk.sign(msg).signature
    return client.patch(
        path,
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Device-Id": device_id,
            "X-Signature-B64": base64.b64encode(sig).decode("ascii"),
        },
    )


@pytest.fixture
def app_with_lib(tmp_path):
    app = create_app(library_db_path=tmp_path / "library.db")
    app.state.library_dirs.add(tmp_path)
    sample = {
        "version": 1,
        "audio_path": str(tmp_path / "meet.mp3"),
        "duration_seconds": 60.0,
        "language": "en",
        "speakers": {"SPEAKER_00": "Alice"},
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": "hi"}],
        "models": {"asr": "faster-whisper:tiny"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (tmp_path / "meet.json").write_text(json.dumps(sample))
    return app


def test_list_transcripts_returns_metadata(app_with_lib):
    client = TestClient(app_with_lib)
    r = client.get("/transcripts")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    item = items[0]
    assert item["id"] == "meet"
    assert item["duration_seconds"] == 60.0
    assert item["speakers"] == 1


def test_get_transcript_returns_full_json(app_with_lib):
    client = TestClient(app_with_lib)
    r = client.get("/transcripts/meet")
    assert r.status_code == 200
    assert r.json()["segments"][0]["text"] == "hi"


def test_patch_relabel_rewrites_sidecar(app_with_lib, tmp_path):
    client = TestClient(app_with_lib)
    r = client.patch("/transcripts/meet/relabel", json={"SPEAKER_00": "Bob"})
    assert r.status_code == 200
    raw = json.loads((tmp_path / "meet.json").read_text())
    assert raw["speakers"]["SPEAKER_00"] == "Bob"


# ── PATCH /transcripts/{tid} (CRDT op) ─────────────────────────────────────


class TestPatchTranscriptOp:
    """Happy-path PATCH coverage. Each test pairs a device first."""

    def _op(self, op="relabel", key="speakers.SPEAKER_00", value="Bob",
            device="ipad-test", lamport_observed=0):
        return {
            "op": op,
            "key": key,
            "value": value,
            "device": device,
            "lamport_observed": lamport_observed,
        }

    def test_applies_relabel(self, app_with_lib, tmp_path):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        r = _signed_patch(client, sk, dev_id, "/transcripts/meet", self._op())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["speakers"]["SPEAKER_00"] == "Bob"
        assert body["lamport_assigned"] >= 1
        raw = json.loads((tmp_path / "meet.json").read_text())
        assert raw["speakers"]["SPEAKER_00"] == "Bob"
        assert raw["_clocks"]["speakers.SPEAKER_00"]["device"] == "ipad-test"

    def test_history_grows_on_each_op(self, app_with_lib, tmp_path):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        _signed_patch(
            client, sk, dev_id, "/transcripts/meet", self._op(value="Bob")
        )
        _signed_patch(
            client, sk, dev_id, "/transcripts/meet",
            self._op(value="Carol", lamport_observed=1),
        )
        raw = json.loads((tmp_path / "meet.json").read_text())
        assert len(raw["_history"]) == 2
        assert raw["speakers"]["SPEAKER_00"] == "Carol"

    def test_lamport_strictly_advances(self, app_with_lib):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        r1 = _signed_patch(
            client, sk, dev_id, "/transcripts/meet", self._op(value="V1")
        )
        r2 = _signed_patch(
            client, sk, dev_id, "/transcripts/meet",
            self._op(value="V2", lamport_observed=0),
        )
        assert r2.json()["lamport_assigned"] > r1.json()["lamport_assigned"]

    def test_lww_latest_lamport_wins(self, app_with_lib, tmp_path):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        for v, lobs in [("V1", 0), ("V2", 1), ("V3", 2), ("V_late", 0)]:
            _signed_patch(
                client, sk, dev_id, "/transcripts/meet",
                self._op(value=v, lamport_observed=lobs),
            )
        raw = json.loads((tmp_path / "meet.json").read_text())
        # Hub assigns sequential lamports; the latest call wins.
        assert raw["speakers"]["SPEAKER_00"] == "V_late"
        assert len(raw["_history"]) == 4

    def test_missing_transcript_returns_404(self, app_with_lib):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        r = _signed_patch(
            client, sk, dev_id, "/transcripts/does-not-exist", self._op()
        )
        assert r.status_code == 404

    def test_bad_op_type_returns_400(self, app_with_lib):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        r = _signed_patch(
            client, sk, dev_id, "/transcripts/meet", self._op(op="delete")
        )
        assert r.status_code == 400

    def test_bad_key_returns_400(self, app_with_lib):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        r = _signed_patch(
            client, sk, dev_id, "/transcripts/meet",
            self._op(key="transcript.title"),
        )
        assert r.status_code == 400

    def test_missing_device_field_rejected(self, app_with_lib):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        body = self._op()
        body["device"] = ""
        r = _signed_patch(client, sk, dev_id, "/transcripts/meet", body)
        # Pydantic min_length=1 on the body's "device" field.
        assert r.status_code == 422

    def test_negative_lamport_rejected(self, app_with_lib):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        body = self._op()
        body["lamport_observed"] = -1
        r = _signed_patch(client, sk, dev_id, "/transcripts/meet", body)
        assert r.status_code == 422

    def test_workspace_id_stamped_on_v1_doc(self, app_with_lib, tmp_path):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        raw_before = json.loads((tmp_path / "meet.json").read_text())
        assert "_workspace_id" not in raw_before
        _signed_patch(client, sk, dev_id, "/transcripts/meet", self._op())
        raw_after = json.loads((tmp_path / "meet.json").read_text())
        assert raw_after["_workspace_id"].startswith("ws_")

    def test_response_shape(self, app_with_lib):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        r = _signed_patch(
            client, sk, dev_id, "/transcripts/meet", self._op()
        )
        assert r.status_code == 200
        body = r.json()
        for key in ("applied", "speakers", "_clocks", "_history", "lamport_assigned"):
            assert key in body
        applied = body["applied"]
        for key in ("op", "key", "value", "device", "lamport", "ts"):
            assert key in applied
        assert applied["op"] == "relabel"
        assert applied["device"] == "ipad-test"
        assert applied["from_value"] == "Alice"


# ── PATCH auth (block 5c) ──────────────────────────────────────────────────


class TestPatchTranscriptOpAuth:
    """Signed-request middleware behaviour on PATCH /transcripts/{tid}."""

    def _body(self) -> dict:
        return {
            "op": "relabel",
            "key": "speakers.SPEAKER_00",
            "value": "X",
            "device": "ipad-test",
            "lamport_observed": 0,
        }

    def test_no_headers_returns_401(self, app_with_lib):
        client = TestClient(app_with_lib)
        r = client.patch("/transcripts/meet", json=self._body())
        assert r.status_code == 401
        assert "X-Device-Id" in r.text or "X-Signature-B64" in r.text

    def test_unknown_device_returns_401(self, app_with_lib):
        from nacl.signing import SigningKey

        client = TestClient(app_with_lib)
        sk = SigningKey.generate()
        body_bytes = json.dumps(self._body()).encode("utf-8")
        msg = b"PATCH\n/transcripts/meet\n" + body_bytes
        sig = sk.sign(msg).signature
        r = client.patch(
            "/transcripts/meet",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Device-Id": "dev-unknown000",
                "X-Signature-B64": base64.b64encode(sig).decode("ascii"),
            },
        )
        assert r.status_code == 401
        assert "unknown device" in r.text

    def test_wrong_signing_key_returns_401(self, app_with_lib):
        from nacl.signing import SigningKey

        client = TestClient(app_with_lib)
        _, dev_id = _pair_device(client)
        wrong_sk = SigningKey.generate()
        body_bytes = json.dumps(self._body()).encode("utf-8")
        msg = b"PATCH\n/transcripts/meet\n" + body_bytes
        sig = wrong_sk.sign(msg).signature
        r = client.patch(
            "/transcripts/meet",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Device-Id": dev_id,
                "X-Signature-B64": base64.b64encode(sig).decode("ascii"),
            },
        )
        assert r.status_code == 401

    def test_tampered_body_returns_401(self, app_with_lib):
        """Signing the right bytes but sending different bytes → 401."""
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        signed_body = json.dumps(self._body()).encode("utf-8")
        tampered_body = json.dumps({**self._body(), "value": "TAMPERED"}).encode("utf-8")
        msg = b"PATCH\n/transcripts/meet\n" + signed_body
        sig = sk.sign(msg).signature
        r = client.patch(
            "/transcripts/meet",
            content=tampered_body,
            headers={
                "Content-Type": "application/json",
                "X-Device-Id": dev_id,
                "X-Signature-B64": base64.b64encode(sig).decode("ascii"),
            },
        )
        assert r.status_code == 401

    def test_bad_signature_encoding_returns_401(self, app_with_lib):
        client = TestClient(app_with_lib)
        _, dev_id = _pair_device(client)
        r = client.patch(
            "/transcripts/meet",
            content=json.dumps(self._body()).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Device-Id": dev_id,
                "X-Signature-B64": "$$$ not base64 $$$",
            },
        )
        assert r.status_code == 401

    def test_successful_call_updates_last_seen(self, app_with_lib):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        before = app_with_lib.state.device_registry.get(dev_id)
        assert before["last_seen"] is None
        _signed_patch(
            client, sk, dev_id, "/transcripts/meet", self._body()
        )
        after = app_with_lib.state.device_registry.get(dev_id)
        assert after["last_seen"] is not None
