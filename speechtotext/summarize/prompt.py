"""Build the summarization prompt from a transcript doc dict."""

from __future__ import annotations

# Rough chars-per-token heuristic (OpenAI-family ≈ 4). Deliberately an
# estimate — we avoid a real tokenizer dependency. The default input budget
# is conservative vs. the 262k-context local models so the completion has room.
_CHARS_PER_TOKEN = 4
_DEFAULT_MAX_INPUT_TOKENS = 120_000


class TranscriptTooLongError(ValueError):
    """Transcript prompt exceeds the summarizer's input budget."""


def estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


def check_within_budget(
    messages: list[dict], max_input_tokens: int = _DEFAULT_MAX_INPUT_TOKENS
) -> None:
    total = sum(estimate_tokens(m.get("content", "")) for m in messages)
    if total > max_input_tokens:
        raise TranscriptTooLongError(
            f"transcript is too long to summarize in one pass "
            f"(~{total} tokens estimated, limit {max_input_tokens}); "
            f"chunked summarization is not yet supported"
        )


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
