from pathlib import Path

import pytest

from speechtotext.config import Config, WatchConfig, load_config


def test_default_config_when_no_file(tmp_path: Path):
    cfg = load_config(config_path=tmp_path / "missing.toml")
    assert cfg.backend in {"auto", "cpu", "cuda", "mps"}
    assert cfg.asr_model == "large-v3"
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
