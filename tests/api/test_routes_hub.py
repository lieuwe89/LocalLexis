"""Tests for GET /hub/info — LAN address + TLS pin for the pairing QR.

The endpoint is loopback-only: the desktop UI reaches the API over the
127.0.0.1 socket, while LAN devices (which hit the same FastAPI app on the
HTTPS socket) must not be able to enumerate the host's address + cert pin.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from speechtotext.api import tls
from speechtotext.api.app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(library_db_path=tmp_path / "library.db")


def _loopback_client(app) -> TestClient:
    return TestClient(app, client=("127.0.0.1", 54321))


class TestHubInfoGate:
    def test_loopback_allowed_shape(self, app):
        r = _loopback_client(app).get("/hub/info")
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body.keys()) == {"lan_addresses", "tls_enabled", "tls_spki_b64"}
        assert isinstance(body["lan_addresses"], list)

    def test_non_loopback_404(self, app):
        # A LAN client (non-loopback source) must not see the endpoint.
        lan = TestClient(app, client=("192.168.1.50", 40000))
        r = lan.get("/hub/info")
        assert r.status_code == 404

    def test_lan_addresses_exclude_loopback(self, app):
        body = _loopback_client(app).get("/hub/info").json()
        assert all(not a.startswith("127.") for a in body["lan_addresses"])
        assert "0.0.0.0" not in body["lan_addresses"]


class TestHubInfoTls:
    def test_tls_disabled_no_spki(self, app, monkeypatch):
        monkeypatch.delenv("LOCALLEXIS_TLS_ENABLED", raising=False)
        body = _loopback_client(app).get("/hub/info").json()
        assert body["tls_enabled"] is False
        assert body["tls_spki_b64"] is None

    def test_tls_enabled_includes_matching_spki(self, app, monkeypatch, tmp_path):
        # Generate a throwaway cert and point the route's TLS resolver at
        # it so the test never touches the real app-data dir.
        cert_path, _ = tls.get_or_create_tls(tmp_path / "cfg")
        monkeypatch.setenv("LOCALLEXIS_TLS_ENABLED", "1")
        monkeypatch.setattr(
            "speechtotext.api.routes_hub.get_or_create_tls",
            lambda *a, **k: (cert_path, cert_path),
        )
        body = _loopback_client(app).get("/hub/info").json()
        assert body["tls_enabled"] is True
        assert body["tls_spki_b64"] == tls.spki_fingerprint_b64(cert_path.read_bytes())
