"""Background thread that embeds pending RAG chunks.

Startup is never blocked: the sentence-transformers model loads inside
this thread on the first non-empty batch. A periodic sweep picks up
whatever reconcile/upsert wrote, so nothing needs to poke it for
correctness — poke() just makes new content searchable sooner.
"""
from __future__ import annotations

import logging
import threading

from speechtotext.rag.embedder import EMBED_MODEL, EmbedderError, get_embedder

_log = logging.getLogger(__name__)

SWEEP_SECONDS = 60.0
BATCH = 64


class EmbedWorker:
    def __init__(self, db) -> None:
        self._db = db
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="embed-worker"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def poke(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self._drain()
            except EmbedderError as exc:
                # Model unavailable (no download yet / offline): retry next
                # sweep; semantic features stay off until it loads.
                # Warning on every sweep is deliberate — it's the only signal
                # that semantic search is off.
                _log.warning("embedding unavailable: %s", exc)
                worked = False
            except Exception:
                _log.exception("embed sweep failed")
                worked = False
            if not worked:
                self._wake.wait(timeout=SWEEP_SECONDS)
                self._wake.clear()

    # ponytail: batch is all-or-nothing; a chunk that reliably fails embedding
    # re-blocks its batch each sweep — add per-chunk isolation if that ever
    # happens in practice.
    def _drain(self) -> bool:
        """Embed one pending batch. True if anything was embedded."""
        pending = self._db.pending_chunks(EMBED_MODEL, limit=BATCH)
        if not pending:
            return False
        vecs = get_embedder().embed([text for _, text in pending])
        self._db.store_embeddings(
            EMBED_MODEL,
            int(vecs.shape[1]),
            [(cid, vecs[i].tobytes()) for i, (cid, _) in enumerate(pending)],
        )
        return True
