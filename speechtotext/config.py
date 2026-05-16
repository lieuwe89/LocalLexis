from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Backend = Literal["auto", "cpu", "cuda", "mps"]
_VALID_BACKENDS: frozenset[str] = frozenset({"auto", "cpu", "cuda", "mps"})

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "speechtotext" / "config.toml"
DEFAULT_MODEL_CACHE = Path.home() / ".cache" / "speechtotext" / "models"


@dataclass
class WatchConfig:
    recursive: bool = False
    debounce_seconds: int = 2
    extensions: list[str] = field(
        default_factory=lambda: ["mp3", "wav", "m4a", "mp4", "flac"]
    )


@dataclass
class Config:
    backend: Backend = "auto"
    asr_model: str = "base.en"
    hf_token: str | None = None
    model_cache_dir: Path = field(default_factory=lambda: DEFAULT_MODEL_CACHE)
    default_out_dir: Path | None = None
    watch: WatchConfig = field(default_factory=WatchConfig)


def _expand(p: str) -> Path:
    return Path(os.path.expandvars(p)).expanduser()


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Config:
    if not config_path.exists():
        return Config()

    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)

    backend = raw.get("backend", "auto")
    if backend not in _VALID_BACKENDS:
        raise ValueError(
            f"invalid backend {backend!r}; expected one of {sorted(_VALID_BACKENDS)}"
        )

    watch_raw = raw.get("watch", {}) or {}
    watch = WatchConfig(
        recursive=bool(watch_raw.get("recursive", False)),
        debounce_seconds=int(watch_raw.get("debounce_seconds", 2)),
        extensions=list(
            watch_raw.get("extensions", ["mp3", "wav", "m4a", "mp4", "flac"])
        ),
    )

    return Config(
        backend=backend,  # type: ignore[arg-type]
        asr_model=str(raw.get("asr_model", "base.en")),
        hf_token=raw.get("hf_token"),
        model_cache_dir=_expand(raw.get("model_cache_dir", str(DEFAULT_MODEL_CACHE))),
        default_out_dir=_expand(raw["default_out_dir"])
        if raw.get("default_out_dir")
        else None,
        watch=watch,
    )
