"""Segment-window chunking for RAG.

Pure functions over the transcript doc dict; no DB or model dependencies.
Chunks keep the first segment index and start/end times so a retrieved
chunk can always jump back to a transcript segment in the UI.
"""
from __future__ import annotations

# Word counts approximate tokens well enough for windowing; a real
# tokenizer would add a dependency for no ranking benefit.
TARGET_WORDS = 150
MAX_WORDS = 300


def build_chunks(doc: dict) -> list[dict]:
    """Merge consecutive segments into ~TARGET_WORDS-word chunks.

    Returns [{idx, first_segment, start_time, end_time, text, token_count}].
    A single over-long segment becomes its own chunk (segments are never
    split), so token_count may exceed MAX_WORDS.
    """
    chunks: list[dict] = []
    texts: list[str] = []
    words = 0
    first = 0
    start = None
    end = None

    def flush() -> None:
        nonlocal texts, words, start, end
        if texts:
            chunks.append({
                "idx": len(chunks),
                "first_segment": first,
                "start_time": start,
                "end_time": end,
                "text": " ".join(texts),
                "token_count": words,
            })
        texts, words, start, end = [], 0, None, None

    for i, seg in enumerate(doc.get("segments") or []):
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        n = len(text.split())
        if texts and words + n > MAX_WORDS:
            flush()
        if not texts:
            first = i
            start = seg.get("start")
        texts.append(text)
        words += n
        end = seg.get("end", seg.get("start"))
        if words >= TARGET_WORDS:
            flush()
    flush()
    return chunks
