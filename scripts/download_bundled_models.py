"""Download faster-whisper models that ship with the Tauri app bundle.

Idempotent: skips repos whose snapshot is already on disk. Run before
`pnpm tauri build` (or before bundling for distribution).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIR = REPO_ROOT / "ui" / "src-tauri" / "resources" / "models"

MODELS: list[tuple[str, str]] = [
    # (HF repo_id, local dirname under TARGET_DIR)
    ("Systran/faster-whisper-base.en", "faster-whisper-base.en"),
]

_PRUNE = {".cache", ".gitattributes", "README.md"}


def main() -> int:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    for repo_id, name in MODELS:
        out = TARGET_DIR / name
        marker = out / "model.bin"
        if marker.is_file():
            print(f"[skip] {name} already present at {out}")
            continue
        print(f"[fetch] {repo_id} -> {out}")
        snapshot_download(repo_id=repo_id, local_dir=str(out))
        for junk in _PRUNE:
            p = out / junk
            if p.is_dir():
                shutil.rmtree(p)
            elif p.is_file():
                p.unlink()
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
