"""Bearer-token auth tests for the sidecar HTTP API.

The Tauri launcher sets LOCALLEXIS_API_TOKEN before spawning the sidecar;
when it is set, every request must carry Authorization: Bearer <token>.
When it is unset (e.g. `stt serve` from the CLI), the API stays anonymous
so standalone use still works.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app
from tests.api._signing import signed_headers


TOKEN = "test-token-7e9f4a"


@pytest.fixture
def auth_client(monkeypatch):
    monkeypatch.setenv("LOCALLEXIS_API_TOKEN", TOKEN)
    return TestClient(create_app())


@pytest.fixture
def anon_client(monkeypatch):
    monkeypatch.delenv("LOCALLEXIS_API_TOKEN", raising=False)
    return TestClient(create_app())


def test_health_is_public_when_token_env_set(auth_client):
    # Uptime monitors poll /health without a token; it only returns {"ok": true}.
    r = auth_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_jobs_requires_bearer_when_token_env_set(auth_client):
    r = auth_client.get("/jobs")
    assert r.status_code == 401


def test_jobs_accepts_matching_bearer(auth_client):
    # The web UI's verifyToken() relies on this route being bearer-only.
    r = auth_client.get("/jobs", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200


def test_jobs_rejects_wrong_token(auth_client):
    r = auth_client.get("/jobs", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_jobs_rejects_non_bearer_scheme(auth_client):
    r = auth_client.get("/jobs", headers={"Authorization": f"Basic {TOKEN}"})
    assert r.status_code == 401


def test_protected_route_also_requires_bearer(auth_client):
    # Pick a route that doesn't touch state-heavy fixtures.
    r = auth_client.get("/transcripts")
    assert r.status_code == 401


def test_options_preflight_skips_auth(auth_client):
    # CORS preflight must succeed without a bearer header so the browser
    # can learn the allowed methods before issuing the real request.
    r = auth_client.options(
        "/health",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code in (200, 204)


def test_health_anonymous_when_env_unset(anon_client):
    r = anon_client.get("/health")
    assert r.status_code == 200


def test_protected_route_anonymous_when_env_unset(anon_client):
    r = anon_client.get("/transcripts")
    assert r.status_code == 200


# ── Signed-route bypass (block 5/6 + hardening interaction) ────────────────
#
# When LOCALLEXIS_API_TOKEN is set (production via Tauri launcher), the
# bearer middleware must still step aside for routes that authenticate
# via the device-signed-request dep — otherwise LAN-paired devices can
# never reach /pair, /sync/*, or PATCH /transcripts/{tid}. /pair/tokens
# and admin endpoints stay bearer-gated so only the Tauri webview can
# bootstrap pairing.


def _mint_token(client: TestClient) -> str:
    r = client.post(
        "/pair/tokens", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _pair_lan_device(client: TestClient):
    """Run the full pair flow as a LAN device with no bearer.

    Mint happens via the bearer-gated admin path; everything else is
    the LAN device's view of the world.
    """
    import base64

    from nacl.signing import SigningKey

    token = _mint_token(client)
    sk = SigningKey.generate()
    r = client.post(
        "/pair",
        json={
            "token": token,
            "device_pubkey_b64": base64.b64encode(
                bytes(sk.verify_key)
            ).decode("ascii"),
            "device_name": "phone",
        },
    )
    assert r.status_code == 200, r.text
    return sk, r.json()["device_id"]


def test_pair_endpoint_bypasses_bearer(auth_client):
    """LAN device POSTs /pair with no bearer; token-in-body authenticates."""
    sk, dev_id = _pair_lan_device(auth_client)
    assert dev_id.startswith("dev-")


def test_pair_tokens_still_requires_bearer(auth_client):
    """Admin-only mint — LAN attacker must not be able to bootstrap."""
    r = auth_client.post("/pair/tokens")
    assert r.status_code == 401


def test_signed_sync_snapshot_bypasses_bearer(auth_client):
    """LAN device GETs /sync/snapshot with Ed25519 sig, no bearer."""
    import base64

    sk, dev_id = _pair_lan_device(auth_client)
    r = auth_client.get(
        "/sync/snapshot",
        headers=signed_headers(sk, dev_id, "GET", "/sync/snapshot"),
    )
    assert r.status_code == 200, r.text


def test_signed_patch_transcript_bypasses_bearer(auth_client, tmp_path):
    """LAN device PATCH /transcripts/{tid} with sig, no bearer."""
    import base64
    import json
    from datetime import datetime, timezone

    # Seed a transcript the LAN device can edit.
    auth_client.app.state.library_dirs.add(tmp_path)
    sample = {
        "version": 1,
        "audio_path": str(tmp_path / "meet.mp3"),
        "duration_seconds": 60.0,
        "language": "en",
        "speakers": {"SPEAKER_00": "Alice"},
        "segments": [
            {"start": 0, "end": 1, "speaker": "SPEAKER_00", "text": "hi"}
        ],
        "models": {"asr": "faster-whisper:tiny"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (tmp_path / "meet.json").write_text(json.dumps(sample))

    sk, dev_id = _pair_lan_device(auth_client)
    body = {
        "op": "relabel",
        "key": "speakers.SPEAKER_00",
        "value": "Bob",
        "lamport_observed": 0,
    }
    body_bytes = json.dumps(body).encode("utf-8")
    r = auth_client.patch(
        "/transcripts/meet",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            **signed_headers(sk, dev_id, "PATCH", "/transcripts/meet", body_bytes),
        },
    )
    assert r.status_code == 200, r.text


def test_patch_relabel_still_requires_bearer(auth_client):
    """Admin bulk relabel route — no signed-request dep, stays bearer-gated."""
    r = auth_client.patch(
        "/transcripts/whatever/relabel", json={"SPEAKER_00": "X"}
    )
    assert r.status_code == 401


def test_list_transcripts_still_requires_bearer(auth_client):
    """Admin listing — not exposed to LAN devices."""
    r = auth_client.get("/transcripts")
    assert r.status_code == 401
