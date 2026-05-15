from __future__ import annotations

import subprocess
from pathlib import Path


class IngestError(RuntimeError):
    pass


def normalize_to_wav(src: Path, dst: Path) -> Path:
    if not src.exists():
        raise IngestError(f"input does not exist: {src}")

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(dst),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise IngestError("ffmpeg not found on PATH") from exc

    if result.returncode != 0:
        raise IngestError(result.stderr.strip() or "ffmpeg conversion failed")
    return dst
