from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Backend = Literal["auto", "cpu", "cuda", "mps"]
_VALID_BACKENDS: frozenset[str] = frozenset({"auto", "cpu", "cuda", "mps"})

AsrEngine = Literal["local", "remote"]
_VALID_ASR_ENGINES: frozenset[str] = frozenset({"local", "remote"})

SummarizeProvider = Literal["lemonade", "openrouter", "custom"]
_VALID_SUMMARIZE_PROVIDERS: frozenset[str] = frozenset(
    {"lemonade", "openrouter", "custom"}
)

# FastFlowLM's default serve port; Lemonade Server uses http://127.0.0.1:13305/v1
DEFAULT_REMOTE_ASR_URL = "http://127.0.0.1:52625/v1"
DEFAULT_REMOTE_ASR_MODEL = "whisper-v3"

DEFAULT_SUMMARIZE_BASE_URL = "http://127.0.0.1:13305/api/v1"
DEFAULT_SUMMARIZE_MODEL = "Qwen3-30B-A3B-Instruct-2507-GGUF"

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
class SummarizeConfig:
    provider: SummarizeProvider = "lemonade"
    base_url: str = DEFAULT_SUMMARIZE_BASE_URL
    model: str = DEFAULT_SUMMARIZE_MODEL
    api_key: str | None = None


@dataclass
class Config:
    backend: Backend = "auto"
    asr_model: str = "base.en"
    asr_engine: AsrEngine = "local"
    # CPU threads for local faster-whisper (CTranslate2 intra-op). 0 = library
    # default (~4). Raise on many-core hosts to speed up long transcripts.
    asr_cpu_threads: int = 0
    remote_asr_url: str = DEFAULT_REMOTE_ASR_URL
    remote_asr_model: str = DEFAULT_REMOTE_ASR_MODEL
    hf_token: str | None = None
    model_cache_dir: Path = field(default_factory=lambda: DEFAULT_MODEL_CACHE)
    default_out_dir: Path | None = None
    watch: WatchConfig = field(default_factory=WatchConfig)
    summarize: SummarizeConfig = field(default_factory=SummarizeConfig)


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

    asr_engine = raw.get("asr_engine", "local")
    if asr_engine not in _VALID_ASR_ENGINES:
        raise ValueError(
            f"invalid asr_engine {asr_engine!r}; expected one of {sorted(_VALID_ASR_ENGINES)}"
        )

    watch_raw = raw.get("watch", {}) or {}
    watch = WatchConfig(
        recursive=bool(watch_raw.get("recursive", False)),
        debounce_seconds=int(watch_raw.get("debounce_seconds", 2)),
        extensions=list(
            watch_raw.get("extensions", ["mp3", "wav", "m4a", "mp4", "flac"])
        ),
    )

    summarize_raw = raw.get("summarize", {}) or {}
    summarize_provider = summarize_raw.get("provider", "lemonade")
    if summarize_provider not in _VALID_SUMMARIZE_PROVIDERS:
        raise ValueError(
            f"invalid summarize provider {summarize_provider!r}; "
            f"expected one of {sorted(_VALID_SUMMARIZE_PROVIDERS)}"
        )
    summarize = SummarizeConfig(
        provider=summarize_provider,  # type: ignore[arg-type]
        base_url=str(summarize_raw.get("base_url", DEFAULT_SUMMARIZE_BASE_URL)),
        model=str(summarize_raw.get("model", DEFAULT_SUMMARIZE_MODEL)),
        api_key=summarize_raw.get("api_key"),
    )

    return Config(
        backend=backend,  # type: ignore[arg-type]
        asr_model=str(raw.get("asr_model", "base.en")),
        asr_engine=asr_engine,  # type: ignore[arg-type]
        asr_cpu_threads=int(raw.get("asr_cpu_threads", 0)),
        remote_asr_url=str(raw.get("remote_asr_url", DEFAULT_REMOTE_ASR_URL)),
        remote_asr_model=str(raw.get("remote_asr_model", DEFAULT_REMOTE_ASR_MODEL)),
        hf_token=raw.get("hf_token"),
        model_cache_dir=_expand(raw.get("model_cache_dir", str(DEFAULT_MODEL_CACHE))),
        default_out_dir=_expand(raw["default_out_dir"])
        if raw.get("default_out_dir")
        else None,
        watch=watch,
        summarize=summarize,
    )
