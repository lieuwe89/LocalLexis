from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter

from speechtotext.config import DEFAULT_MODEL_CACHE, load_config

router = APIRouter()

# (name, approx_size_mb). Keep aligned with the Settings dropdown.
_WHISPER_MODELS: tuple[tuple[str, int], ...] = (
    ("tiny", 75),
    ("tiny.en", 75),
    ("base", 140),
    ("base.en", 140),
    ("small", 470),
    ("small.en", 470),
    ("medium", 1500),
    ("medium.en", 1500),
    ("large-v3", 3000),
)


def _bundled_dir_for(name: str) -> Path | None:
    root = os.environ.get("LOCALSCRIBE_BUNDLED_MODELS")
    if not root:
        return None
    cand = Path(root) / f"faster-whisper-{name}"
    return cand if (cand / "model.bin").is_file() else None


def _hf_cache_has(name: str, model_cache_dir: Path) -> bool:
    """A faster-whisper model is "cached" if its HF snapshot dir has a
    model.bin. Faster-whisper downloads with download_root=model_cache_dir
    when configured, else into ~/.cache/huggingface/hub.
    """
    repo_dirname = f"models--Systran--faster-whisper-{name}"
    candidates = [
        model_cache_dir / repo_dirname,
        Path.home() / ".cache" / "huggingface" / "hub" / repo_dirname,
    ]
    for base in candidates:
        snapshots = base / "snapshots"
        if not snapshots.is_dir():
            continue
        for snap in snapshots.iterdir():
            if (snap / "model.bin").is_file():
                return True
    return False


@router.get("/models/whisper")
def list_whisper_models() -> list[dict]:
    try:
        cfg = load_config()
        model_cache_dir = cfg.model_cache_dir
    except Exception:
        model_cache_dir = DEFAULT_MODEL_CACHE

    out: list[dict] = []
    for name, size_mb in _WHISPER_MODELS:
        if _bundled_dir_for(name) is not None:
            status = "bundled"
        elif _hf_cache_has(name, model_cache_dir):
            status = "cached"
        else:
            status = "not_downloaded"
        out.append({"name": name, "status": status, "size_mb": size_mb})
    return out
