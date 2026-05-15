from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from speechtotext.models import Transcript

_SCHEMA_VERSION = 1


def _format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_txt(t: Transcript) -> str:
    lines: list[str] = []
    for seg in t.segments:
        display = t.speakers.get(seg.speaker_id, seg.speaker_id)
        lines.append(f"[{_format_timestamp(seg.start)}] {display}: {seg.text}")
    return "\n".join(lines) + ("\n" if lines else "")


def _serialize(t: Transcript) -> dict:
    return {
        "version": _SCHEMA_VERSION,
        "audio_path": str(t.audio_path),
        "duration_seconds": t.duration_seconds,
        "language": t.language,
        "speakers": dict(t.speakers),
        "segments": [
            {
                "start": s.start,
                "end": s.end,
                "speaker": s.speaker_id,
                "text": s.text,
            }
            for s in t.segments
        ],
        "models": dict(t.models),
        "created_at": t.created_at.isoformat(),
    }


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def write_transcript(t: Transcript) -> tuple[Path, Path]:
    audio = t.audio_path
    txt_path = audio.with_suffix(".txt")
    json_path = audio.with_suffix(".json")

    txt_content = format_txt(t)
    json_content = json.dumps(_serialize(t), indent=2, ensure_ascii=False)

    _atomic_write(txt_path, txt_content)
    _atomic_write(json_path, json_content)
    return txt_path, json_path
