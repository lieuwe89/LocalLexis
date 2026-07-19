"""Best-sentence highlighting for semantic search hits.

Semantic matches have no lexical span to mark; instead we mark the
sentence in each hit's chunk whose embedding sits closest to the query.
Runs hub-side, on the hits actually returned (not all candidates).
ponytail: dozens of hits x ~10 sentences per query, batch-embedded on a
warm MiniLM — subsecond on CPU. Revisit if libraries grow hundredfold.
"""
from __future__ import annotations

import re

import numpy as np

_SENT_RE = re.compile(r"(?<=[.!?])\s+")
_CONTEXT_CHARS = 120


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENT_RE.split(text) if s.strip()]


def _trim_pre(text: str) -> str:
    return text if len(text) <= _CONTEXT_CHARS else "…" + text[-_CONTEXT_CHARS:]


def _trim_post(text: str) -> str:
    return text if len(text) <= _CONTEXT_CHARS else text[:_CONTEXT_CHARS] + "…"


def mark_hits(items: list[dict], query_vec, embed) -> None:
    """Rewrite each hit's snippet_parts in place to mark the sentence closest
    to the query. `embed(texts) -> np.ndarray` (unit-normalized rows). Best
    effort: on any failure the hit falls back to a plain truncated snippet."""
    qv = np.asarray(query_vec, dtype=np.float32)
    for item in items:
        for hit in item.get("hits") or []:
            text = "".join(p["text"] for p in hit.get("snippet_parts") or [])
            if not text.strip():
                continue
            try:
                sentences = split_sentences(text)
                if not sentences:
                    continue
                if len(sentences) == 1:
                    # A whole-chunk mark highlights nothing meaningful (and a
                    # punctuation-less chunk can be hundreds of words) — show
                    # the plain bounded snippet instead.
                    hit["snippet_parts"] = [{"text": text[:200], "match": False}]
                    continue
                vecs = embed(sentences)
                best = int(np.argmax(vecs @ qv))
                # Locate the best sentence by cumulative offset, not .index():
                # a sentence that also occurs as a substring earlier in the
                # text would otherwise mark the wrong span.
                offset = 0
                for i, s in enumerate(sentences):
                    pos = text.find(s, offset)
                    if i == best:
                        start, end = pos, pos + len(s)
                        break
                    offset = pos + len(s)
                pre, mid, post = text[:start], text[start:end], text[end:]
                parts = []
                if pre.strip():
                    parts.append({"text": _trim_pre(pre), "match": False})
                parts.append({"text": mid, "match": True})
                if post.strip():
                    parts.append({"text": _trim_post(post), "match": False})
                hit["snippet_parts"] = parts
            except Exception:  # noqa: BLE001 — highlighting is best-effort
                hit["snippet_parts"] = [{"text": text[:200], "match": False}]
        if item.get("hits"):
            item["snippet_parts"] = item["hits"][0]["snippet_parts"]
