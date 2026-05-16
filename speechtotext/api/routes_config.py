from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from speechtotext.config import DEFAULT_CONFIG_PATH, load_config

router = APIRouter()


def _public(cfg) -> dict:
    return {
        "backend": cfg.backend,
        "asr_model": cfg.asr_model,
        "hf_token_set": bool(cfg.hf_token),
        "model_cache_dir": str(cfg.model_cache_dir),
        "default_out_dir": str(cfg.default_out_dir) if cfg.default_out_dir else None,
        "watch": {
            "recursive": cfg.watch.recursive,
            "debounce_seconds": cfg.watch.debounce_seconds,
            "extensions": list(cfg.watch.extensions),
        },
    }


@router.get("/config")
def get_config() -> dict:
    cfg = load_config(config_path=DEFAULT_CONFIG_PATH)
    return _public(cfg)


@router.patch("/config")
def patch_config(updates: dict[str, Any]) -> dict:
    path: Path = DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        import tomllib
        existing = tomllib.loads(path.read_text())
    existing.update({k: v for k, v in updates.items() if not isinstance(v, dict)})
    if isinstance(updates.get("watch"), dict):
        existing.setdefault("watch", {}).update(updates["watch"])

    def _dump_toml(d: dict) -> str:
        lines: list[str] = []
        for k, v in d.items():
            if k == "watch":
                continue
            lines.append(_kv(k, v))
        if "watch" in d:
            lines.append("\n[watch]")
            for k, v in d["watch"].items():
                lines.append(_kv(k, v))
        return "\n".join(lines) + "\n"

    def _kv(k: str, v) -> str:
        if isinstance(v, bool):
            return f"{k} = {'true' if v else 'false'}"
        if isinstance(v, (int, float)):
            return f"{k} = {v}"
        if isinstance(v, list):
            inside = ", ".join(f'"{x}"' for x in v)
            return f"{k} = [{inside}]"
        return f'{k} = "{v}"'

    path.write_text(_dump_toml(existing), encoding="utf-8")
    return _public(load_config(config_path=path))
