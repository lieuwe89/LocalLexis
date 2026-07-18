"""Lazy in-process sentence-transformers embedder.

The model (~470MB with deps on first download) loads on first use — never
at import time and never during sidecar startup. All callers share one
instance via get_embedder().
"""
from __future__ import annotations

import threading

import numpy as np

EMBED_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


class EmbedderError(RuntimeError):
    """Model missing / download failed — semantic features unavailable."""


class Embedder:
    def __init__(self, model_name: str = EMBED_MODEL) -> None:
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                except Exception as exc:  # pragma: no cover - import failure
                    raise EmbedderError(
                        f"embedding model unavailable: {exc}"
                    ) from exc
                # Privacy invariant: once the model is cached, loading it must
                # make zero network calls. Try local-files-only first; only
                # fall back to a network fetch on the very first-ever load
                # (model not yet cached).
                try:
                    self._model = SentenceTransformer(
                        self.model_name, local_files_only=True
                    )
                except Exception:
                    try:
                        self._model = SentenceTransformer(self.model_name)
                    except Exception as exc:
                        raise EmbedderError(
                            f"embedding model unavailable: {exc}"
                        ) from exc
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        """Unit-normalized float32 vectors, shape (len(texts), dim)."""
        model = self._load()
        vecs = model.encode(
            texts, normalize_embeddings=True, convert_to_numpy=True
        )
        return np.asarray(vecs, dtype=np.float32)


_instance: Embedder | None = None
_instance_lock = threading.Lock()


def get_embedder() -> Embedder:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = Embedder()
        return _instance
