from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import tomllib
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator

from speechtotext.config import DEFAULT_CONFIG_PATH, load_config

router = APIRouter()

# Serialise the read-modify-write of config.toml. Two concurrent PATCH
# /config requests would otherwise both read the same state and the second
# write would silently drop the first request's change.
_config_write_lock = threading.Lock()

_EXT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_TOP_KEYS = (
    "backend",
    "asr_model",
    "asr_engine",
    "remote_asr_url",
    "remote_asr_model",
    "hf_token",
    "model_cache_dir",
    "default_out_dir",
)
_WATCH_KEYS = ("recursive", "debounce_seconds", "extensions")
_SUMMARIZE_KEYS = ("provider", "base_url", "model", "api_key")


class WatchPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recursive: bool | None = None
    debounce_seconds: int | None = Field(default=None, ge=0, le=3600)
    extensions: list[str] | None = None

    @field_validator("extensions")
    @classmethod
    def _ext_strings_valid(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        for ext in v:
            if not isinstance(ext, str) or not _EXT_RE.match(ext):
                raise ValueError(f"invalid extension: {ext!r}")
        return v


class SummarizePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["lemonade", "openrouter", "custom"] | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    model: str | None = Field(default=None, min_length=1, max_length=256)
    api_key: str | None = Field(default=None, max_length=512)

    @field_validator("base_url", "model", "api_key")
    @classmethod
    def _no_null_bytes(cls, v: str | None) -> str | None:
        if v is not None and "\x00" in v:
            raise ValueError("null byte in value")
        return v


class ConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: Literal["auto", "cpu", "cuda", "mps"] | None = None
    asr_model: str | None = Field(default=None, min_length=1, max_length=128)
    asr_engine: Literal["local", "remote"] | None = None
    remote_asr_url: str | None = Field(default=None, min_length=1, max_length=2048)
    remote_asr_model: str | None = Field(default=None, min_length=1, max_length=128)
    hf_token: str | None = Field(default=None, max_length=512)
    model_cache_dir: str | None = Field(default=None, max_length=4096)
    default_out_dir: str | None = Field(default=None, max_length=4096)
    watch: WatchPatch | None = None
    summarize: SummarizePatch | None = None

    @field_validator(
        "asr_model",
        "remote_asr_url",
        "remote_asr_model",
        "hf_token",
        "model_cache_dir",
        "default_out_dir",
    )
    @classmethod
    def _no_null_bytes(cls, v: str | None) -> str | None:
        if v is not None and "\x00" in v:
            raise ValueError("null byte in value")
        return v


def _public(cfg) -> dict:
    return {
        "backend": cfg.backend,
        "asr_model": cfg.asr_model,
        "asr_engine": cfg.asr_engine,
        "remote_asr_url": cfg.remote_asr_url,
        "remote_asr_model": cfg.remote_asr_model,
        "hf_token_set": bool(cfg.hf_token),
        "model_cache_dir": str(cfg.model_cache_dir),
        "default_out_dir": str(cfg.default_out_dir) if cfg.default_out_dir else None,
        "watch": {
            "recursive": cfg.watch.recursive,
            "debounce_seconds": cfg.watch.debounce_seconds,
            "extensions": list(cfg.watch.extensions),
        },
        "summarize": {
            "provider": cfg.summarize.provider,
            "base_url": cfg.summarize.base_url,
            "model": cfg.summarize.model,
            "api_key_set": bool(cfg.summarize.api_key),
        },
    }


def _toml_value(v: Any) -> str:
    # bool must come before int (bool is a subclass of int)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        # JSON basic-string escapes are a strict subset of TOML basic-string
        # escapes, so json.dumps produces a valid TOML literal for any
        # validator-accepted string (no raw control chars, no null bytes).
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"unsupported TOML value: {type(v).__name__}")


def _dump_toml(d: dict[str, Any]) -> str:
    lines: list[str] = []
    for k in _TOP_KEYS:
        if k in d:
            lines.append(f"{k} = {_toml_value(d[k])}")
    watch = d.get("watch")
    if isinstance(watch, dict):
        lines.append("")
        lines.append("[watch]")
        for k in _WATCH_KEYS:
            if k in watch:
                lines.append(f"{k} = {_toml_value(watch[k])}")
    summarize = d.get("summarize")
    if isinstance(summarize, dict):
        lines.append("")
        lines.append("[summarize]")
        for k in _SUMMARIZE_KEYS:
            if k in summarize:
                lines.append(f"{k} = {_toml_value(summarize[k])}")
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cfg.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@router.get("/config")
def get_config() -> dict:
    cfg = load_config(config_path=DEFAULT_CONFIG_PATH)
    return _public(cfg)


@router.patch("/config")
def patch_config(updates: ConfigPatch) -> dict:
    path: Path = DEFAULT_CONFIG_PATH

    patch = updates.model_dump(exclude_none=True)

    with _config_write_lock:
        existing: dict[str, Any] = {}
        if path.exists():
            existing = tomllib.loads(path.read_text(encoding="utf-8"))

        for k in _TOP_KEYS:
            if k in patch:
                existing[k] = patch[k]

        if "watch" in patch:
            watch_existing = existing.get("watch")
            if not isinstance(watch_existing, dict):
                watch_existing = {}
            for k, v in patch["watch"].items():
                watch_existing[k] = v
            existing["watch"] = watch_existing

        if "summarize" in patch:
            summarize_existing = existing.get("summarize")
            if not isinstance(summarize_existing, dict):
                summarize_existing = {}
            for k, v in patch["summarize"].items():
                summarize_existing[k] = v
            existing["summarize"] = summarize_existing

        _atomic_write(path, _dump_toml(existing))
        return _public(load_config(config_path=path))
