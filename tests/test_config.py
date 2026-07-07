from pathlib import Path

import pytest

from speechtotext.config import Config, WatchConfig, load_config


def test_default_config_when_no_file(tmp_path: Path):
    cfg = load_config(config_path=tmp_path / "missing.toml")
    assert cfg.backend in {"auto", "cpu", "cuda", "mps"}
    assert cfg.asr_model == "base.en"
    assert cfg.hf_token is None
    assert cfg.default_out_dir is None
    assert cfg.watch.recursive is False
    assert cfg.watch.debounce_seconds == 2
    assert "wav" in cfg.watch.extensions


def test_loads_from_toml(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '''
backend = "cuda"
asr_model = "medium"
hf_token = "hf_abc"
model_cache_dir = "~/cache"
default_out_dir = "/tmp/out"

[watch]
recursive = true
debounce_seconds = 5
extensions = ["mp3", "flac"]
'''
    )
    cfg = load_config(config_path=cfg_file)
    assert cfg.backend == "cuda"
    assert cfg.asr_model == "medium"
    assert cfg.hf_token == "hf_abc"
    assert cfg.model_cache_dir == Path("~/cache").expanduser()
    assert cfg.default_out_dir == Path("/tmp/out")
    assert cfg.watch.recursive is True
    assert cfg.watch.debounce_seconds == 5
    assert cfg.watch.extensions == ["mp3", "flac"]


def test_invalid_backend_rejected(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('backend = "tpu"\n')
    with pytest.raises(ValueError, match="backend"):
        load_config(config_path=cfg_file)


def test_asr_engine_defaults_local(tmp_path: Path):
    cfg = load_config(config_path=tmp_path / "missing.toml")
    assert cfg.asr_engine == "local"
    assert cfg.remote_asr_url == "http://127.0.0.1:52625/v1"
    assert cfg.remote_asr_model == "whisper-v3"


def test_asr_engine_remote_from_toml(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '''
asr_engine = "remote"
remote_asr_url = "http://hub:13305/v1"
remote_asr_model = "whisper-large-v3-turbo"
'''
    )
    cfg = load_config(config_path=cfg_file)
    assert cfg.asr_engine == "remote"
    assert cfg.remote_asr_url == "http://hub:13305/v1"
    assert cfg.remote_asr_model == "whisper-large-v3-turbo"


def test_invalid_asr_engine_rejected(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('asr_engine = "npu"\n')
    with pytest.raises(ValueError, match="asr_engine"):
        load_config(config_path=cfg_file)


def test_summarize_defaults_and_parse(tmp_path: Path):
    cfg = load_config(config_path=tmp_path / "missing.toml")
    assert cfg.summarize.provider == "lemonade"
    assert cfg.summarize.base_url == "http://127.0.0.1:13305/api/v1"
    assert cfg.summarize.model == "Qwen3-30B-A3B-Instruct-2507-GGUF"
    assert cfg.summarize.api_key is None

    f = tmp_path / "c.toml"
    f.write_text('[summarize]\nprovider = "openrouter"\nmodel = "X"\napi_key = "k"\n')
    cfg = load_config(config_path=f)
    assert cfg.summarize.provider == "openrouter"
    assert cfg.summarize.model == "X"
    assert cfg.summarize.api_key == "k"


def test_summarize_invalid_provider_raises(tmp_path: Path):
    cfg_file = tmp_path / "c.toml"
    cfg_file.write_text('[summarize]\nprovider = "nope"\n')
    with pytest.raises(ValueError, match="summarize"):
        load_config(config_path=cfg_file)
