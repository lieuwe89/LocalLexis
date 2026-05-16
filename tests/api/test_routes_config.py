import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


def test_config_get_returns_defaults_and_hf_flag(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("speechtotext.api.routes_config.DEFAULT_CONFIG_PATH", cfg_path)
    app = create_app()
    r = TestClient(app).get("/config")
    assert r.status_code == 200
    body = r.json()
    assert body["backend"] == "auto"
    assert body["hf_token_set"] is False


def test_config_patch_writes_toml(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("speechtotext.api.routes_config.DEFAULT_CONFIG_PATH", cfg_path)
    app = create_app()
    r = TestClient(app).patch("/config", json={"asr_model": "small", "hf_token": "hf_xxx"})
    assert r.status_code == 200
    raw = tomllib.loads(cfg_path.read_text())
    assert raw["asr_model"] == "small"
    assert raw["hf_token"] == "hf_xxx"


def test_config_patch_float_debounce_round_trips(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr("speechtotext.api.routes_config.DEFAULT_CONFIG_PATH", cfg_path)
    app = create_app()
    r = TestClient(app).patch("/config", json={"watch": {"debounce_seconds": 2.5}})
    assert r.status_code == 200
    raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    assert raw["watch"]["debounce_seconds"] == 2.5
