from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("speechtotext.api.routes_config.DEFAULT_CONFIG_PATH", cfg_path)
    app = create_app()
    return TestClient(app), cfg_path


def test_get_config_has_summarize_defaults(client):
    c, _ = client
    cfg = c.get("/config").json()
    s = cfg["summarize"]
    assert s["provider"] == "lemonade"
    assert s["base_url"] == "http://127.0.0.1:13305/api/v1"
    assert s["model"] == "Qwen3-30B-A3B-Instruct-2507-GGUF"
    assert s["api_key_set"] is False


def test_patch_summarize_round_trips(client):
    c, _ = client
    r = c.patch(
        "/config",
        json={
            "summarize": {
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "model": "meta-llama/llama-3.3-70b-instruct",
                "api_key": "sk-secret",
            }
        },
    )
    assert r.status_code == 200
    s = r.json()["summarize"]
    assert s["provider"] == "openrouter"
    assert s["api_key_set"] is True
    assert "sk-secret" not in str(r.json())  # never echoed


def test_patch_summarize_partial(client):
    c, _ = client
    c.patch("/config", json={"summarize": {"model": "Qwen3-8B-GGUF"}})
    s = c.get("/config").json()["summarize"]
    assert s["model"] == "Qwen3-8B-GGUF"
    assert s["provider"] == "lemonade"  # untouched


def test_patch_summarize_bad_provider_422(client):
    c, _ = client
    r = c.patch("/config", json={"summarize": {"provider": "carrier-pigeon"}})
    assert r.status_code == 422
