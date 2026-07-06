from pathlib import Path
from fastapi.testclient import TestClient
from speechtotext.api.app import create_app

import speechtotext.api.app as _app_module


def _seed_webui(tmp_path: Path, monkeypatch):
    webui = tmp_path / "webui"
    webui.mkdir()
    (webui / "index.html").write_text("<!doctype html><title>hub</title>", encoding="utf-8")
    # Patch the live module object directly rather than by string path:
    # a string path walks speechtotext.api.app via parent-attribute lookup,
    # which breaks across tests that wipe sys.modules (e.g.
    # test_sidecar_cold_start); see tests/api/conftest.py for context.
    monkeypatch.setattr(_app_module, "WEBUI_DIR", webui)


def test_app_serves_webui_when_enabled(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALLEXIS_API_TOKEN", raising=False)
    _seed_webui(tmp_path, monkeypatch)
    app = create_app(serve_webui=True)
    c = TestClient(app)
    r = c.get("/app/")
    assert r.status_code == 200
    assert "hub" in r.text


def test_webui_absent_by_default(tmp_path, monkeypatch):
    _seed_webui(tmp_path, monkeypatch)
    app = create_app()  # serve_webui defaults False (loopback sidecar)
    c = TestClient(app)
    assert c.get("/app/").status_code == 404


def test_webui_assets_reachable_without_token(tmp_path, monkeypatch):
    # Login page must load before the user has a token.
    monkeypatch.setenv("LOCALLEXIS_API_TOKEN", "secret")
    _seed_webui(tmp_path, monkeypatch)
    app = create_app(serve_webui=True)
    c = TestClient(app)
    r = c.get("/app/")  # no Authorization header
    assert r.status_code == 200
