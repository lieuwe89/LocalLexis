"""Best-sentence highlighting for semantic search hits."""
from __future__ import annotations

import numpy as np
import pytest

from speechtotext.rag import highlight as mod
from speechtotext.rag.embedder import EmbedderError


def _hit(text: str) -> dict:
    return {"snippet_parts": [{"text": text, "match": False}]}


def _items(text: str) -> list[dict]:
    return [{"hits": [_hit(text)]}]


def test_marks_best_sentence():
    text = "Zin een hier. Zin twee is het. Zin drie sluit af."
    vecs = {
        "Zin een hier.": np.array([1.0, 0.0, 0.0], dtype=np.float32),
        "Zin twee is het.": np.array([0.0, 1.0, 0.0], dtype=np.float32),
        "Zin drie sluit af.": np.array([0.0, 0.0, 1.0], dtype=np.float32),
    }

    def embed(texts):
        return np.vstack([vecs[t] for t in texts])

    items = _items(text)
    qv = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    mod.mark_hits(items, qv, embed)

    parts = items[0]["hits"][0]["snippet_parts"]
    assert [p["match"] for p in parts] == [False, True, False]
    assert parts[1]["text"] == "Zin twee is het."
    # nothing lost: joining the original (untrimmed) spans covers the text
    assert parts[0]["text"] + parts[1]["text"] + parts[2]["text"] == text


def test_single_sentence_falls_back_to_plain_snippet():
    text = "Slechts een enkele zin zonder punt"
    items = _items(text)

    def embed(texts):
        raise AssertionError("embed should not be called for a single sentence")

    mod.mark_hits(items, np.zeros(3, dtype=np.float32), embed)
    parts = items[0]["hits"][0]["snippet_parts"]
    assert len(parts) == 1
    assert parts[0]["match"] is False
    assert parts[0]["text"] == text[:200]


def test_long_context_trimmed_with_ellipsis():
    pre_sentence = "X" * 150 + "."
    best_sentence = "Best sentence match."
    post_sentence = "Y" * 150 + "."
    text = f"{pre_sentence} {best_sentence} {post_sentence}"
    vecs = {
        pre_sentence: np.array([1.0, 0.0, 0.0], dtype=np.float32),
        best_sentence: np.array([0.0, 1.0, 0.0], dtype=np.float32),
        post_sentence: np.array([0.0, 0.0, 1.0], dtype=np.float32),
    }

    def embed(texts):
        return np.vstack([vecs[t] for t in texts])

    items = _items(text)
    qv = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    mod.mark_hits(items, qv, embed)

    parts = items[0]["hits"][0]["snippet_parts"]
    assert parts[1]["text"] == best_sentence
    assert parts[1]["match"] is True
    assert parts[0]["text"].startswith("…")
    assert parts[-1]["text"].endswith("…")
    assert len(parts[0]["text"]) <= 121
    assert len(parts[-1]["text"]) <= 121


def test_embed_failure_falls_back_to_truncated_plain():
    text = "Eerste zin hier. Tweede zin hier. Derde zin hier."

    def embed(texts):
        raise EmbedderError("embedding model unavailable: x")

    items = _items(text)
    mod.mark_hits(items, np.zeros(3, dtype=np.float32), embed)
    parts = items[0]["hits"][0]["snippet_parts"]
    assert parts == [{"text": text[:200], "match": False}]


def test_split_sentences_edge_cases():
    assert mod.split_sentences("") == []
    assert mod.split_sentences("geen leestekens hier") == ["geen leestekens hier"]

    # An abbreviation may split the sentence imperfectly, but mark_hits must
    # not crash and the parts must still re-cover the original text.
    text = "Dr. X zegt iets. Tweede zin."
    sentences = mod.split_sentences(text)
    assert len(sentences) >= 1

    def embed(texts):
        return np.tile(np.array([1.0, 0.0], dtype=np.float32), (len(texts), 1))

    items = _items(text)
    mod.mark_hits(items, np.array([1.0, 0.0], dtype=np.float32), embed)
    parts = items[0]["hits"][0]["snippet_parts"]
    assert "".join(p["text"] for p in parts) == text


def test_mark_hits_skips_empty_text():
    items = [{"hits": [_hit("")]}]

    def embed(texts):
        raise AssertionError("must not be called for empty text")

    mod.mark_hits(items, np.zeros(3, dtype=np.float32), embed)
    # untouched: still the original (empty) snippet_parts
    assert items[0]["hits"][0]["snippet_parts"] == [{"text": "", "match": False}]
