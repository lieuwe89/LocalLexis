from __future__ import annotations

import json
from pathlib import Path


def scan_dirs(dirs: set[Path]) -> list[dict]:
    out: list[dict] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for json_path in d.glob("*.json"):
            try:
                raw = json.loads(json_path.read_text(encoding="utf-8"))
                out.append({
                    "id": json_path.stem,
                    "path": str(json_path),
                    "audio_path": raw.get("audio_path"),
                    "duration_seconds": raw.get("duration_seconds"),
                    "language": raw.get("language"),
                    "speakers": len(raw.get("speakers", {})),
                    "created_at": raw.get("created_at"),
                    "models": raw.get("models", {}),
                })
            except (json.JSONDecodeError, OSError):
                out.append({"id": json_path.stem, "path": str(json_path), "error": "parse"})
    out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return out


def find_sidecar(dirs: set[Path], transcript_id: str) -> Path | None:
    for d in dirs:
        candidate = d / f"{transcript_id}.json"
        if candidate.exists():
            return candidate
    return None
