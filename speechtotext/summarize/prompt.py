"""Build the summarization prompt from a transcript doc dict."""

from __future__ import annotations

_SYSTEM = (
    "You are a precise assistant that summarizes meeting and voice-note "
    "transcripts. Write in the transcript's language. Output markdown with: "
    "a 2-3 sentence overview, key points as bullets, and (only when present) "
    "decisions and action items as separate bullet lists. Do not invent "
    "content that is not in the transcript."
)


def build_summary_messages(doc: dict) -> list[dict]:
    speakers = doc.get("speakers") or {}
    lines: list[str] = []
    for seg in doc.get("segments") or []:
        spk = seg.get("speaker", "")
        display = speakers.get(spk, spk)
        lines.append(f"{display}: {seg.get('text', '')}")
    title = doc.get("title") or ""
    head = f"Transcript{f' — {title}' if title else ''}\n\n"
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": head + "\n".join(lines)},
    ]
