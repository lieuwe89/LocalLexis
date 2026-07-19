"""Auth on the hub proxy surface: GET /transcripts, POST /library/ask,
GET /jobs/{job_id}.

A joined laptop calls these on the hub with device-signed requests, so
when a bearer token is configured they must accept EITHER the admin
bearer OR a valid Ed25519 device signature (verify_admin_or_device_or_
anonymous). In authless mode (no LOCALLEXIS_API_TOKEN) they must stay
fully anonymous — the standalone `stt serve` contract.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app
from tests.api._signing import signed_headers

TOKEN = "proxy-secret-9c1d"
BEARER = {"Authorization": f"Bearer {TOKEN}"}


def _pair_device(client: TestClient):
    """Pair a fresh device (authless phase). Returns (signing_key, device_id)."""
    from nacl.signing import SigningKey

    token = client.post("/pair/tokens").json()["token"]
    sk = SigningKey.generate()
    r = client.post(
        "/pair",
        json={
            "token": token,
            "device_pubkey_b64": base64.b64encode(bytes(sk.verify_key)).decode(
                "ascii"
            ),
            "device_name": "proxy-test-device",
        },
    )
    assert r.status_code == 200, r.text
    return sk, r.json()["device_id"]


@pytest.fixture
def noop_ask(monkeypatch):
    """POST /library/ask tests assert AUTH, not the ask pipeline."""
    from speechtotext.api import runner

    monkeypatch.setattr(runner, "run_ask_job", lambda *a, **k: None)


@pytest.fixture
def paired(tmp_path, monkeypatch):
    """App with a paired device AND a bearer token configured.

    Pairing happens while the env is unset (the pair bootstrap routes are
    bearer-gated in token mode); the token is set afterwards, so every
    request in the test body runs against an auth-enabled hub.
    """
    monkeypatch.delenv("LOCALLEXIS_API_TOKEN", raising=False)
    app = create_app(
        library_db_path=tmp_path / "library.db",
        devices_db_path=tmp_path / "devices.db",
    )
    client = TestClient(app)
    sk, dev_id = _pair_device(client)
    monkeypatch.setenv("LOCALLEXIS_API_TOKEN", TOKEN)
    return client, app, sk, dev_id


@pytest.fixture
def anon(tmp_path, monkeypatch):
    """Authless app: no token, no pairing — the standalone-serve mode."""
    monkeypatch.delenv("LOCALLEXIS_API_TOKEN", raising=False)
    app = create_app(
        library_db_path=tmp_path / "library.db",
        devices_db_path=tmp_path / "devices.db",
    )
    return TestClient(app), app


# ── device-signed requests accepted (token configured) ─────────────────────


def test_device_signed_get_transcripts_accepted(paired):
    client, _, sk, dev_id = paired
    path = "/transcripts?q=x"
    r = client.get(path, headers=signed_headers(sk, dev_id, "GET", path))
    assert r.status_code == 200, r.text


def test_device_signed_post_ask_accepted(paired, noop_ask):
    client, _, sk, dev_id = paired
    body = json.dumps({"question": "x"}).encode("utf-8")
    r = client.post(
        "/library/ask",
        content=body,
        headers={
            "Content-Type": "application/json",
            **signed_headers(sk, dev_id, "POST", "/library/ask", body),
        },
    )
    assert r.status_code == 202, r.text
    assert "job_id" in r.json()


def test_device_signed_get_job_accepted(paired):
    client, app, sk, dev_id = paired
    job_id = app.state.jobs.create(kind="ask", audio_path=None)
    path = f"/jobs/{job_id}"
    r = client.get(path, headers=signed_headers(sk, dev_id, "GET", path))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == job_id


# ── no bearer + no signature → 401 (token configured) ──────────────────────


def test_unsigned_requests_still_401(paired):
    client, app, _, _ = paired
    job_id = app.state.jobs.create(kind="ask", audio_path=None)
    assert client.get("/transcripts").status_code == 401
    assert client.post("/library/ask", json={"question": "x"}).status_code == 401
    assert client.get(f"/jobs/{job_id}").status_code == 401


# ── admin bearer unchanged (token configured) ──────────────────────────────


def test_admin_bearer_still_works(paired, noop_ask):
    client, app, _, _ = paired
    job_id = app.state.jobs.create(kind="ask", audio_path=None)
    assert client.get("/transcripts", headers=BEARER).status_code == 200
    assert (
        client.post(
            "/library/ask", json={"question": "x"}, headers=BEARER
        ).status_code
        == 202
    )
    assert client.get(f"/jobs/{job_id}", headers=BEARER).status_code == 200


# ── authless mode stays anonymous (regression guard) ───────────────────────


def test_authless_mode_still_anonymous(anon, noop_ask):
    """No token configured → bare requests keep working (standalone serve)."""
    client, app = anon
    job_id = app.state.jobs.create(kind="ask", audio_path=None)
    assert client.get("/transcripts").status_code == 200
    assert client.post("/library/ask", json={"question": "x"}).status_code == 202
    assert client.get(f"/jobs/{job_id}").status_code == 200


# ── the /jobs matcher must not open other job routes ───────────────────────


def test_jobs_list_and_mutations_stay_bearer_gated(paired):
    client, _, sk, dev_id = paired
    # GET /jobs (list) is NOT on the signed surface: middleware 401s it
    # even with a valid signature.
    r = client.get("/jobs", headers=signed_headers(sk, dev_id, "GET", "/jobs"))
    assert r.status_code == 401
    # POST mutations under /jobs/* stay bearer-gated too.
    assert client.post("/jobs/some-id/cancel").status_code == 401
    # GET /jobs/{id}/stream is not matched by the single-segment regex.
    assert client.get("/jobs/some-id/stream").status_code == 401
