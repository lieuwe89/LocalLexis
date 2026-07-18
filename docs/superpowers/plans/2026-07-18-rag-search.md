# RAG Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Semantic search as a toggle on the existing library search, plus a library-wide "Ask" Q&A panel with clickable sources, per `docs/superpowers/specs/2026-07-18-rag-search-design.md`.

**Architecture:** Pure chunker + lazy in-process sentence-transformers embedder in a new `speechtotext/rag/` package. `LibraryDB` stores chunks (written during `upsert_path`) and embeddings (written by a background `EmbedWorker` thread), and answers vector queries with a brute-force numpy dot-product over an in-memory matrix cache. Q&A runs as a job (like summarize) through the existing `OpenAICompatProvider`.

**Tech Stack:** Python 3.11, FastAPI, SQLite, numpy, sentence-transformers (`paraphrase-multilingual-MiniLM-L12-v2` — 384 dims, NL+EN), React/zustand UI.

**Key existing anchors:**
- `speechtotext/api/library_db.py` — `LibraryDB`, `SCHEMA_VERSION = 2`, `_DDL` already contains empty `chunks` + `embeddings` tables, `upsert_path`, `search`, `_row_to_item`.
- `speechtotext/api/routes_transcripts.py:119` — `GET /transcripts` with `q`/`fuzzy`/`sort`.
- `speechtotext/api/runner.py:207` — `run_summarize_job` (the job pattern to mirror).
- `speechtotext/api/jobs.py` — `JobRegistry`, `JobRecord`.
- `speechtotext/api/routes_jobs.py:47` — `_job_dict`.
- `speechtotext/summarize/prompt.py` — `build_summary_messages` lives here; add `build_ask_messages` beside it.
- `speechtotext/api/app.py:129` — `_lifespan`; state wiring around line 178; router includes around line 295.
- `ui/src/stores/library.ts` — `fuzzy`/`setFuzzy` pattern to mirror for `semantic`.
- `ui/src/screens/LibraryScreen.tsx:80-86` — the fuzzy toggle button to mirror.
- `ui/src/stores/transcripts.ts:46-55` — `summarize` job-polling pattern to mirror for ask.

**Migration strategy:** bump `SCHEMA_VERSION` 2→3 and add `first_segment` to the `chunks` DDL. The existing drop-and-rebuild migration re-indexes every known file (`known_paths` mechanism, see `_migrate`), which repopulates `chunks` for the whole library. Embeddings are then backfilled by the `EmbedWorker`. No ALTER, no bespoke backfill code.

**Test conventions:** `tests/api/conftest.py` has an autouse fixture isolating app-data dirs. Library DB tests build docs with a `_make_doc`-style helper (see `tests/api/test_library_db_segments.py`). New pure-Python RAG tests go in `tests/rag/`.

---

### Task 1: Dependency + chunker

**Files:**
- Modify: `pyproject.toml` (api extra, around line 33)
- Create: `speechtotext/rag/__init__.py` (empty)
- Create: `speechtotext/rag/chunker.py`
- Create: `tests/rag/__init__.py` (empty)
- Test: `tests/rag/test_chunker.py`

- [ ] **Step 1: Add sentence-transformers to the api extra**

In `pyproject.toml`, inside the `api = [` list of `[project.optional-dependencies]`, add:

```toml
    "sentence-transformers>=3.0",
```

Also append `sentence-transformers>=3.0` on its own line to `requirements-server-cpu.txt` if that file pins api deps (check; if it only pins torch/ASR deps, skip it and note that in the commit message).

- [ ] **Step 2: Write the failing chunker test**

Create `tests/rag/__init__.py` (empty) and `tests/rag/test_chunker.py`:

```python
from __future__ import annotations

from speechtotext.rag.chunker import MAX_WORDS, TARGET_WORDS, build_chunks


def _doc(segments):
    return {"segments": [
        {"start": s, "end": e, "speaker": "SPEAKER_00", "text": t}
        for s, e, t in segments
    ]}


def test_merges_short_segments_until_target():
    # 3 segments of 60 words each; target 150 → first chunk holds seg 0+1+2? No:
    # 60+60=120 < 150, +60=180 ≥ 150 → one chunk of 180 words.
    seg = " ".join(["woord"] * 60)
    doc = _doc([(0.0, 5.0, seg), (5.0, 10.0, seg), (10.0, 15.0, seg)])
    chunks = build_chunks(doc)
    assert len(chunks) == 1
    assert chunks[0]["token_count"] == 180
    assert chunks[0]["idx"] == 0
    assert chunks[0]["first_segment"] == 0
    assert chunks[0]["start_time"] == 0.0
    assert chunks[0]["end_time"] == 15.0


def test_max_words_starts_new_chunk():
    # 200 + 200 words: second segment would exceed MAX_WORDS=300 → two chunks.
    seg = " ".join(["woord"] * 200)
    doc = _doc([(0.0, 5.0, seg), (5.0, 10.0, seg)])
    chunks = build_chunks(doc)
    assert len(chunks) == 2
    assert chunks[1]["idx"] == 1
    assert chunks[1]["first_segment"] == 1
    assert chunks[1]["start_time"] == 5.0


def test_single_overlong_segment_is_one_chunk():
    seg = " ".join(["woord"] * (MAX_WORDS + 50))
    chunks = build_chunks(_doc([(0.0, 9.0, seg)]))
    assert len(chunks) == 1
    assert chunks[0]["token_count"] == MAX_WORDS + 50


def test_empty_and_blank_segments_skipped():
    assert build_chunks({"segments": []}) == []
    assert build_chunks({}) == []
    chunks = build_chunks(_doc([(0.0, 1.0, "   "), (1.0, 2.0, "hallo daar")]))
    assert len(chunks) == 1
    assert chunks[0]["first_segment"] == 1
    assert chunks[0]["text"] == "hallo daar"


def test_constants_sane():
    assert 0 < TARGET_WORDS < MAX_WORDS
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/lieuwejongsma/SpeechToText && python -m pytest tests/rag/test_chunker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'speechtotext.rag'`

- [ ] **Step 4: Implement the chunker**

Create `speechtotext/rag/__init__.py` (empty) and `speechtotext/rag/chunker.py`:

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/rag/test_chunker.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements-server-cpu.txt speechtotext/rag tests/rag
git commit -m "feat(rag): segment-window chunker + sentence-transformers dep"
```

---

### Task 2: Lazy embedder

**Files:**
- Create: `speechtotext/rag/embedder.py`
- Test: `tests/rag/test_embedder.py`

- [ ] **Step 1: Write the failing test**

Create `tests/rag/test_embedder.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from speechtotext.rag import embedder as mod


class _FakeModel:
    def encode(self, texts, normalize_embeddings=True, convert_to_numpy=True):
        # deterministic 4-dim unit vectors keyed on text length
        out = []
        for t in texts:
            v = np.array([len(t), 1.0, 0.0, 0.0], dtype=np.float64)
            out.append(v / np.linalg.norm(v))
        return np.vstack(out)


def test_embed_returns_float32_normalized(monkeypatch):
    e = mod.Embedder()
    monkeypatch.setattr(e, "_load", lambda: _FakeModel())
    vecs = e.embed(["hallo", "langere zin hier"])
    assert vecs.dtype == np.float32
    assert vecs.shape == (2, 4)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-5)


def test_load_failure_raises_embedder_error(monkeypatch):
    e = mod.Embedder(model_name="nonexistent/nope")

    def boom():
        raise mod.EmbedderError("embedding model unavailable: x")

    monkeypatch.setattr(e, "_load", boom)
    with pytest.raises(mod.EmbedderError):
        e.embed(["hallo"])


def test_get_embedder_is_singleton():
    a = mod.get_embedder()
    b = mod.get_embedder()
    assert a is b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/rag/test_embedder.py -v`
Expected: FAIL with `ModuleNotFoundError` (no `speechtotext.rag.embedder`)

- [ ] **Step 3: Implement the embedder**

Create `speechtotext/rag/embedder.py`:

```python
"""Lazy in-process sentence-transformers embedder.

The model (~470MB with deps on first download) loads on first use — never
at import time and never during sidecar startup. All callers share one
instance via get_embedder().
"""
from __future__ import annotations

import threading

import numpy as np

EMBED_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
EMBED_DIM = 384


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
                    self._model = SentenceTransformer(self.model_name)
                except Exception as exc:  # ImportError, download/IO failure
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/rag/test_embedder.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add speechtotext/rag/embedder.py tests/rag/test_embedder.py
git commit -m "feat(rag): lazy singleton sentence-transformers embedder"
```

---

### Task 3: Chunk storage in LibraryDB (schema v3)

**Files:**
- Modify: `speechtotext/api/library_db.py` (SCHEMA_VERSION, `_DDL` chunks, `__init__`, `upsert_path`, `delete_by_path`)
- Test: `tests/api/test_rag_library_db.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_rag_library_db.py` (helpers copied from `tests/api/test_library_db_segments.py` — repeat them, tasks may run out of order):

```python
"""Chunk + embedding storage and semantic search in LibraryDB."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from speechtotext.api.library_db import LibraryDB


def _make_doc(text_segments, audio_name: str = "meeting.mp3") -> dict:
    return {
        "version": 1,
        "audio_path": f"/some/dir/{audio_name}",
        "duration_seconds": text_segments[-1][1] if text_segments else 0.0,
        "language": "nl",
        "speakers": {"SPEAKER_00": "Alice"},
        "segments": [
            {"start": s, "end": e, "speaker": "SPEAKER_00", "text": t}
            for s, e, t in text_segments
        ],
        "models": {"asr": "faster-whisper:base"},
        "created_at": "2026-07-18T12:00:00+00:00",
    }


def _write(dir: Path, name: str, doc: dict) -> Path:
    p = dir / f"{name}.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


@pytest.fixture
def db(tmp_path: Path) -> LibraryDB:
    return LibraryDB(tmp_path / "library.db")


def _chunk_rows(db: LibraryDB, tid: str):
    return db._conn.execute(
        "SELECT * FROM chunks WHERE transcript_id=? ORDER BY idx", (tid,)
    ).fetchall()


def test_upsert_writes_chunks(db: LibraryDB, tmp_path: Path):
    long = " ".join(["woord"] * 200)
    p = _write(tmp_path, "alpha", _make_doc([(0.0, 5.0, long), (5.0, 9.0, long)]))
    db.upsert_path(p)
    rows = _chunk_rows(db, "alpha")
    assert len(rows) == 2
    assert rows[0]["first_segment"] == 0
    assert rows[1]["first_segment"] == 1
    assert rows[0]["text"].startswith("woord")


```

Write ONLY `test_upsert_writes_chunks` in this task. The cascade test (re-upsert drops embeddings) needs `store_embeddings` and is added in Task 4 as:

```python
def test_reupsert_replaces_chunks_and_drops_embeddings(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "alpha", _make_doc([(0.0, 5.0, "hallo wereld")]))
    db.upsert_path(p)
    cid = _chunk_rows(db, "alpha")[0]["id"]
    vec = np.ones(4, dtype=np.float32)
    db.store_embeddings("m", 4, [(cid, vec.tobytes())])
    # re-upsert → chunks replaced, embedding cascades away
    db.upsert_path(p)
    assert len(_chunk_rows(db, "alpha")) == 1
    n = db._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    assert n == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_rag_library_db.py::test_upsert_writes_chunks -v`
Expected: FAIL — `chunks` has no `first_segment` column / zero rows written

- [ ] **Step 3: Implement schema v3 + chunk writes**

In `speechtotext/api/library_db.py`:

1. `SCHEMA_VERSION = 2` → `SCHEMA_VERSION = 3` (line 40). The existing drop-and-rebuild migration carries `known_paths` and re-indexes every file, which populates chunks for existing libraries.
2. Import the chunker at the top with the phonetics import:

```python
from speechtotext.rag.chunker import build_chunks
```

3. In `_DDL`, replace the `chunks` table definition with (adds `first_segment`):

```python
    """
    CREATE TABLE IF NOT EXISTS chunks (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
        idx           INTEGER NOT NULL,
        first_segment INTEGER,
        start_time    REAL,
        end_time      REAL,
        text          TEXT NOT NULL,
        token_count   INTEGER,
        version       INTEGER NOT NULL DEFAULT 1,
        UNIQUE(transcript_id, idx)
    )
    """,
```

4. In `__init__` (after `self._lock = ...`), add the vector-matrix cache slot:

```python
        # (model, matrix, metas) — invalidated on any chunk/embedding write.
        self._vec_cache: tuple | None = None
```

5. In `upsert_path`, inside the `with self._lock, self._conn:` block, after the segments loop (after line ~516), add:

```python
            # RAG chunks: replace wholesale; embeddings cascade away and the
            # EmbedWorker re-embeds on its next sweep.
            self._conn.execute("DELETE FROM chunks WHERE transcript_id=?", (tid,))
            for ch in build_chunks(doc):
                self._conn.execute(
                    "INSERT INTO chunks (transcript_id, idx, first_segment, "
                    "start_time, end_time, text, token_count) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (tid, ch["idx"], ch["first_segment"], ch["start_time"],
                     ch["end_time"], ch["text"], ch["token_count"]),
                )
            self._vec_cache = None
```

6. In `delete_by_path`, after the transcript row delete, add `self._vec_cache = None` (inside the lock).

- [ ] **Step 4: Run tests to verify pass — including migration tests**

Run: `python -m pytest tests/api/test_rag_library_db.py tests/api/test_library_db.py tests/api/test_library_db_segments.py tests/api/test_library_dirs_persistence.py -v`
Expected: PASS (schema-version tests may assert `2` — update any that hardcode it to import `SCHEMA_VERSION` instead)

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/library_db.py tests/api/test_rag_library_db.py
git commit -m "feat(rag): schema v3 — chunks written on upsert, rebuild repopulates"
```

---

### Task 4: Embedding storage + vector search in LibraryDB

**Files:**
- Modify: `speechtotext/api/library_db.py`
- Test: `tests/api/test_rag_library_db.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/api/test_rag_library_db.py` (and enable the cascade test from Task 3):

```python
def _embed_all(db: LibraryDB, model: str = "test-model"):
    """Deterministic fake embeddings: unit vector keyed on first word."""
    pend = db.pending_chunks(model, limit=1000)
    rows = []
    for cid, text in pend:
        seed = float(len(text.split()[0]))
        v = np.array([seed, 1.0, 0.0], dtype=np.float64)
        v = (v / np.linalg.norm(v)).astype(np.float32)
        rows.append((cid, v.tobytes()))
    db.store_embeddings(model, 3, rows)


def test_pending_then_store_then_none_pending(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "alpha", _make_doc([(0.0, 5.0, "hallo wereld dit is tekst")]))
    db.upsert_path(p)
    assert len(db.pending_chunks("test-model")) == 1
    _embed_all(db)
    assert db.pending_chunks("test-model") == []


def test_model_change_makes_chunks_pending_again(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "alpha", _make_doc([(0.0, 5.0, "hallo wereld")]))
    db.upsert_path(p)
    _embed_all(db, model="old-model")
    assert len(db.pending_chunks("new-model")) == 1


def test_top_chunks_ranks_by_similarity(db: LibraryDB, tmp_path: Path):
    doc_a = _make_doc([(0.0, 5.0, "kort verhaal")], audio_name="a.mp3")
    doc_b = _make_doc([(0.0, 5.0, "aanzienlijk langer eerste woord hier")], audio_name="b.mp3")
    db.upsert_path(_write(tmp_path, "alpha", doc_a))
    db.upsert_path(_write(tmp_path, "beta", doc_b))
    _embed_all(db)
    # query = exact fake-embedding of "kort" (len 4) → alpha's chunk wins
    q = np.array([4.0, 1.0, 0.0], dtype=np.float64)
    q = (q / np.linalg.norm(q)).astype(np.float32)
    top = db.top_chunks(q, "test-model", k=2)
    assert top[0]["transcript_id"] == "alpha"
    assert top[0]["score"] > top[1]["score"]
    assert "first_segment" in top[0] and "text" in top[0]


def test_semantic_search_groups_hits_per_transcript(db: LibraryDB, tmp_path: Path):
    db.upsert_path(_write(tmp_path, "alpha", _make_doc([(0.0, 5.0, "kort verhaal")])))
    _embed_all(db)
    q = np.array([4.0, 1.0, 0.0], dtype=np.float64)
    q = (q / np.linalg.norm(q)).astype(np.float32)
    items = db.semantic_search(q, "test-model", limit=10)
    assert len(items) == 1
    item = items[0]
    assert item["id"] == "alpha"
    assert item["hits"][0]["segment_index"] == 0
    assert item["hits"][0]["snippet_parts"][0]["text"].startswith("kort")
    assert item["total_hits"] == 1


def test_semantic_search_empty_index_returns_empty(db: LibraryDB):
    q = np.zeros(3, dtype=np.float32)
    assert db.semantic_search(q, "test-model") == []


def test_store_embeddings_invalidates_cache(db: LibraryDB, tmp_path: Path):
    db.upsert_path(_write(tmp_path, "alpha", _make_doc([(0.0, 5.0, "kort verhaal")])))
    _embed_all(db)
    q = np.array([4.0, 1.0, 0.0], dtype=np.float32)
    q = q / np.linalg.norm(q)
    assert len(db.top_chunks(q, "test-model", k=5)) == 1  # warms cache
    db.upsert_path(_write(tmp_path, "beta", _make_doc([(0.0, 5.0, "kort ander")], audio_name="b.mp3")))
    _embed_all(db)
    assert len(db.top_chunks(q, "test-model", k=5)) == 2  # cache rebuilt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/api/test_rag_library_db.py -v`
Expected: FAIL with `AttributeError: 'LibraryDB' object has no attribute 'pending_chunks'`

- [ ] **Step 3: Implement embedding storage + vector search**

Add `import numpy as np` to the top-level imports of `library_db.py`. Add a module constant near `_HITS_PER_TRANSCRIPT`:

```python
# Cosine floor for semantic hits: below this, chunks are noise, not matches.
# ponytail: fixed heuristic threshold; make configurable only if users report
# missing/irrelevant semantic results.
_MIN_SIM = 0.25
```

Add these methods to `LibraryDB` (after `search`, before `get_path`):

```python
    # ── RAG: embeddings + vector search ───────────────────────────────────

    def pending_chunks(self, model: str, limit: int = 256) -> list[tuple[int, str]]:
        """Chunks lacking an embedding for `model` (or embedded by another)."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT c.id, c.text FROM chunks c
                LEFT JOIN embeddings e ON e.chunk_id = c.id
                WHERE e.chunk_id IS NULL OR e.model != ?
                LIMIT ?
                """,
                (model, limit),
            ).fetchall()
        return [(r["id"], r["text"]) for r in rows]

    def store_embeddings(
        self, model: str, dim: int, rows: list[tuple[int, bytes]]
    ) -> None:
        """rows = [(chunk_id, float32-le vector bytes)]."""
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO embeddings (chunk_id, model, dim, vector) "
                "VALUES (?, ?, ?, ?)",
                [(cid, model, dim, blob) for cid, blob in rows],
            )
            self._vec_cache = None

    def _vec_matrix(self, model: str):
        """(matrix, metas) over all embeddings for `model`, cached until a
        chunk/embedding write. ponytail: full in-memory brute-force matrix;
        switch to sqlite-vec if a library ever exceeds ~500k chunks."""
        with self._lock:
            cached = self._vec_cache
            if cached is not None and cached[0] == model:
                return cached[1], cached[2]
            rows = self._conn.execute(
                """
                SELECT e.vector, c.transcript_id, c.first_segment,
                       c.start_time, c.text
                FROM embeddings e JOIN chunks c ON c.id = e.chunk_id
                WHERE e.model = ?
                """,
                (model,),
            ).fetchall()
            if rows:
                mat = np.vstack([
                    np.frombuffer(r["vector"], dtype=np.float32) for r in rows
                ])
                metas = [
                    {
                        "transcript_id": r["transcript_id"],
                        "first_segment": r["first_segment"],
                        "start": r["start_time"],
                        "text": r["text"],
                    }
                    for r in rows
                ]
            else:
                mat = np.zeros((0, 1), dtype=np.float32)
                metas = []
            self._vec_cache = (model, mat, metas)
            return mat, metas

    def top_chunks(self, query_vec, model: str, k: int = 8) -> list[dict]:
        """k best chunks by cosine similarity (vectors are unit-normalized)."""
        mat, metas = self._vec_matrix(model)
        if mat.shape[0] == 0:
            return []
        sims = mat @ np.asarray(query_vec, dtype=np.float32)
        order = np.argsort(-sims)[:k]
        return [
            {**metas[i], "score": float(sims[i])}
            for i in order
            if sims[i] >= _MIN_SIM
        ]

    def semantic_search(self, query_vec, model: str, limit: int = 50) -> list[dict]:
        """Chunk hits grouped per transcript, in the FTS search() hit format
        (snippet_parts carry match=False: there is no lexical span to mark)."""
        top = self.top_chunks(query_vec, model, k=limit * 4)
        if not top:
            return []
        by_tid: dict[str, list[dict]] = {}
        for c in top:
            by_tid.setdefault(c["transcript_id"], []).append(c)

        qmarks = ",".join("?" for _ in by_tid)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT id, json_path, audio_path, title, duration_seconds,
                       language, speakers_count, created_at,
                       models_asr, models_diarizer, error, origin
                FROM transcripts WHERE id IN ({qmarks})
                """,
                list(by_tid),
            ).fetchall()
        items_by_id = {r["id"]: self._row_to_item(r) for r in rows}

        items: list[dict] = []
        for tid, chunks in by_tid.items():
            item = items_by_id.get(tid)
            if item is None:
                continue  # row vanished between queries
            hits = [
                {
                    "segment_index": c["first_segment"],
                    "start": c["start"],
                    "snippet_parts": [{"text": c["text"][:200], "match": False}],
                    "score": c["score"],
                }
                for c in chunks  # already similarity-ordered from top_chunks
            ]
            item["hits"] = hits[:_HITS_PER_TRANSCRIPT]
            item["total_hits"] = len(hits)
            item["snippet_parts"] = hits[0]["snippet_parts"]
            item["_best"] = hits[0]["score"]
            items.append(item)
        items.sort(key=lambda i: -i.pop("_best"))
        return items[:limit]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/api/test_rag_library_db.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/library_db.py tests/api/test_rag_library_db.py
git commit -m "feat(rag): embedding storage + brute-force semantic search in LibraryDB"
```

---

### Task 5: Background EmbedWorker

**Files:**
- Create: `speechtotext/api/embed_worker.py`
- Modify: `speechtotext/api/app.py` (state + lifespan)
- Test: `tests/api/test_embed_worker.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_embed_worker.py`:

```python
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

from speechtotext.api import embed_worker as mod
from speechtotext.api.library_db import LibraryDB
from speechtotext.rag.embedder import EMBED_MODEL


class _FakeEmbedder:
    def embed(self, texts):
        return np.ones((len(texts), 4), dtype=np.float32)


@pytest.fixture
def db(tmp_path: Path) -> LibraryDB:
    d = LibraryDB(tmp_path / "library.db")
    doc = {
        "audio_path": "/x/a.mp3",
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "S", "text": "hallo wereld"}],
        "created_at": "2026-07-18T12:00:00+00:00",
    }
    p = tmp_path / "alpha.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    d.upsert_path(p)
    return d


def test_drain_embeds_pending(db, monkeypatch):
    monkeypatch.setattr(mod, "get_embedder", lambda: _FakeEmbedder())
    w = mod.EmbedWorker(db)
    assert w._drain() is True          # embedded one batch
    assert w._drain() is False         # nothing left
    assert db.pending_chunks(EMBED_MODEL) == []


def test_worker_thread_drains_on_poke(db, monkeypatch):
    monkeypatch.setattr(mod, "get_embedder", lambda: _FakeEmbedder())
    w = mod.EmbedWorker(db)
    w.start()
    try:
        w.poke()
        deadline = time.time() + 5
        while db.pending_chunks(EMBED_MODEL) and time.time() < deadline:
            time.sleep(0.02)
        assert db.pending_chunks(EMBED_MODEL) == []
    finally:
        w.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_embed_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'speechtotext.api.embed_worker'`

- [ ] **Step 3: Implement the worker**

Create `speechtotext/api/embed_worker.py`:

```python
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
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="embed-worker"
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def poke(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self._drain()
            except EmbedderError as exc:
                # Model unavailable (no download yet / offline): retry next
                # sweep; semantic features stay off until it loads.
                _log.warning("embedding unavailable: %s", exc)
                worked = False
            except Exception:
                _log.exception("embed sweep failed")
                worked = False
            if not worked:
                self._wake.wait(timeout=SWEEP_SECONDS)
                self._wake.clear()

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
```

- [ ] **Step 4: Wire into app.py**

In `speechtotext/api/app.py`:
- Import: `from speechtotext.api.embed_worker import EmbedWorker` (with the other api imports near line 20).
- After `app.state.library_reconciler = ...` (line 184): `app.state.embed_worker = EmbedWorker(app.state.library_db)`.
- In `_lifespan`, after the startup `sync_dirs` thread is started (line ~138): `app.state.embed_worker.start()`.
- In `_lifespan` shutdown (next to `app.state.hub_runtime.stop()`, line 154): `app.state.embed_worker.stop()`.

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest tests/api/test_embed_worker.py tests/api/test_app.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add speechtotext/api/embed_worker.py speechtotext/api/app.py tests/api/test_embed_worker.py
git commit -m "feat(rag): background embed worker, started from app lifespan"
```

---

### Task 6: `semantic=1` on GET /transcripts

**Files:**
- Modify: `speechtotext/api/routes_transcripts.py:119-136`
- Test: `tests/api/test_semantic_search_route.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_semantic_search_route.py`. Use the same app-construction pattern as `tests/api/test_routes_transcripts.py` (open that file and copy its client/app fixture verbatim — typically `create_app(...)` + `fastapi.testclient.TestClient` with a tmp library dir):

```python
from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app
from speechtotext.rag import embedder as rag_embedder


class _FakeEmbedder:
    def embed(self, texts):
        v = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
        return np.repeat(v, len(texts), axis=0)


@pytest.fixture
def client(tmp_path):
    doc = {
        "audio_path": str(tmp_path / "a.mp3"),
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "S", "text": "hallo wereld"}],
        "created_at": "2026-07-18T12:00:00+00:00",
    }
    (tmp_path / "alpha.json").write_text(json.dumps(doc), encoding="utf-8")
    app = create_app(library_dirs=[tmp_path], library_db_path=tmp_path / "lib.db")
    with TestClient(app) as c:
        yield c, app


def _embed_all(db):
    pend = db.pending_chunks(rag_embedder.EMBED_MODEL, limit=100)
    vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    db.store_embeddings(
        rag_embedder.EMBED_MODEL, 3, [(cid, vec.tobytes()) for cid, _ in pend]
    )


def test_semantic_search_returns_hits(client, monkeypatch):
    c, app = client
    monkeypatch.setattr(rag_embedder, "get_embedder", lambda: _FakeEmbedder())
    _embed_all(app.state.library_db)
    r = c.get("/transcripts", params={"q": "groet", "semantic": 1})
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["id"] == "alpha"
    assert items[0]["hits"][0]["segment_index"] == 0


def test_semantic_unavailable_returns_503(client, monkeypatch):
    c, _ = client

    class _Broken:
        def embed(self, texts):
            raise rag_embedder.EmbedderError("embedding model unavailable: x")

    monkeypatch.setattr(rag_embedder, "get_embedder", lambda: _Broken())
    r = c.get("/transcripts", params={"q": "groet", "semantic": 1})
    assert r.status_code == 503


def test_without_semantic_flag_fts_path_unchanged(client):
    c, _ = client
    r = c.get("/transcripts", params={"q": "hallo"})
    assert r.status_code == 200
    assert r.json()[0]["id"] == "alpha"
```

(Adjust the `create_app(...)` signature to what `tests/api/test_routes_transcripts.py` actually uses — e.g. if the fixture passes `default_out_dir` or uses a helper, mirror that exactly.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_semantic_search_route.py -v`
Expected: `test_semantic_search_returns_hits` FAILS (unknown param → falls through to FTS which won't match "groet")

- [ ] **Step 3: Implement the route param**

In `speechtotext/api/routes_transcripts.py`, add a module-level import (safe: sentence-transformers loads lazily inside `_load`):

```python
from speechtotext.rag import embedder as rag_embedder
```

Change `list_transcripts` (line 119):

```python
@router.get("/transcripts")
def list_transcripts(
    request: Request,
    q: str | None = Query(default=None, description="full-text search query"),
    limit: int = Query(default=200, ge=1, le=1000),
    fuzzy: bool = Query(default=False, description="also match phonetically"),
    sort: str = Query(default="relevance", pattern="^(relevance|date)$"),
    semantic: bool = Query(default=False, description="match by meaning (embeddings)"),
) -> list[dict]:
    db = request.app.state.library_db
    request.app.state.library_reconciler.reconcile(set(request.app.state.library_dirs))
    if q and semantic:
        try:
            qvec = rag_embedder.get_embedder().embed([q])[0]
        except rag_embedder.EmbedderError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        return db.semantic_search(qvec, rag_embedder.EMBED_MODEL, limit=limit)
    if q:
        return db.search(q, limit=limit, fuzzy=fuzzy, sort=sort)
    return db.list(limit=limit)
```

(Keep the existing reconcile comment block above the reconcile call.)

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/api/test_semantic_search_route.py tests/api/test_routes_transcripts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/routes_transcripts.py tests/api/test_semantic_search_route.py
git commit -m "feat(api): semantic=1 vector search on GET /transcripts"
```

---

### Task 7: UI — semantic toggle

**Files:**
- Modify: `ui/src/stores/library.ts`
- Modify: `ui/src/screens/LibraryScreen.tsx` (toggle row, lines 80-94)
- Test: `ui/src/stores/library.test.ts` (extend)

- [ ] **Step 1: Write the failing store test**

In `ui/src/stores/library.test.ts`, mirror the existing fuzzy-toggle test (read the file first and copy its mock setup) and add:

```ts
it('setSemantic re-runs the current search with semantic=1', async () => {
  // mirror the setFuzzy test's api mock arrangement
  useLibrary.setState({ query: 'begroeting' });
  await useLibrary.getState().setSemantic(true);
  const calledUrl = vi.mocked(api).mock.calls.at(-1)![0] as string;
  expect(calledUrl).toContain('semantic=1');
});

it('search omits semantic param when toggle is off', async () => {
  useLibrary.setState({ semantic: false });
  await useLibrary.getState().search('hallo');
  const calledUrl = vi.mocked(api).mock.calls.at(-1)![0] as string;
  expect(calledUrl).not.toContain('semantic');
});
```

(Adapt `setState`/mock details to the file's existing conventions — the assertion targets are the URL contents.)

- [ ] **Step 2: Run to verify fail**

Run: `cd ui && npx vitest run src/stores/library.test.ts`
Expected: FAIL — `setSemantic` is not a function

- [ ] **Step 3: Implement store + screen**

`ui/src/stores/library.ts` — mirror `fuzzy` exactly:
- State: add `semantic: boolean;` and `setSemantic: (v: boolean) => void;` to the interface; `semantic: false,` to the initial state.
- In `search`, next to the existing `if (fuzzy) url += '&fuzzy=1';` read `semantic` from `get()` and add:

```ts
    if (semantic) url += '&semantic=1';
```

- Add next to `setFuzzy` (copy its shape, including the re-search):

```ts
  setSemantic: (v: boolean) => {
    set({ semantic: v });
    const q = get().query;
    if (q.trim()) void get().search(q);
  },
```

`ui/src/screens/LibraryScreen.tsx` — after the fuzzy toggle button (line 86), add:

```tsx
        <button
          className={'lib-toggle' + (semantic ? ' on' : '')}
          aria-label="Semantic search"
          aria-pressed={semantic}
          title="Semantic search — match by meaning instead of exact words"
          onClick={() => setSemantic(!semantic)}
        >≈ meaning</button>
```

with the selectors added next to the fuzzy ones (line 42-43):

```tsx
  const semantic = useLibrary(s => s.semantic);
  const setSemantic = useLibrary(s => s.setSemantic);
```

- [ ] **Step 4: Run UI tests**

Run: `cd ui && npx vitest run src/stores/library.test.ts src/screens/LibraryScreen.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ui/src/stores/library.ts ui/src/screens/LibraryScreen.tsx ui/src/stores/library.test.ts
git commit -m "feat(ui): semantic search toggle in library search bar"
```

---

### Task 8: Ask job (runner + prompt + JobRecord.result)

**Files:**
- Modify: `speechtotext/api/jobs.py:32-42` (JobRecord)
- Modify: `speechtotext/api/routes_jobs.py:47-58` (`_job_dict`)
- Modify: `speechtotext/summarize/prompt.py` (add `build_ask_messages`)
- Modify: `speechtotext/api/runner.py` (add `run_ask_job`)
- Test: `tests/api/test_ask_job.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_ask_job.py`:

```python
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

from speechtotext.api import runner as runner_mod
from speechtotext.api.jobs import JobRegistry, JobStatus
from speechtotext.api.library_db import LibraryDB
from speechtotext.rag import embedder as rag_embedder
from speechtotext.summarize.prompt import build_ask_messages


class _FakeEmbedder:
    def embed(self, texts):
        v = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
        return np.repeat(v, len(texts), axis=0)


class _FakeProvider:
    model = "fake-model"

    def chat(self, messages):
        assert any("Question:" in m["content"] for m in messages)
        return "Het antwoord is 42 [1]."


@pytest.fixture
def db(tmp_path: Path) -> LibraryDB:
    d = LibraryDB(tmp_path / "library.db")
    doc = {
        "audio_path": "/x/a.mp3",
        "segments": [{"start": 12.0, "end": 15.0, "speaker": "S", "text": "het antwoord is tweeenveertig"}],
        "created_at": "2026-07-18T12:00:00+00:00",
    }
    p = tmp_path / "alpha.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    d.upsert_path(p)
    vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    pend = d.pending_chunks(rag_embedder.EMBED_MODEL, limit=10)
    d.store_embeddings(rag_embedder.EMBED_MODEL, 3, [(cid, vec.tobytes()) for cid, _ in pend])
    return d


def _wait(registry, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = registry.get(job_id)
        if rec.status in (JobStatus.complete, JobStatus.failed):
            return rec
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_build_ask_messages_numbers_excerpts():
    msgs = build_ask_messages("wat is het antwoord?", [
        {"transcript_id": "alpha", "first_segment": 0, "start": 12.0,
         "text": "het antwoord is 42", "score": 0.9},
    ])
    assert msgs[0]["role"] == "system"
    assert "[1]" in msgs[1]["content"]
    assert "wat is het antwoord?" in msgs[1]["content"]


def test_run_ask_job_sets_result(db, monkeypatch):
    monkeypatch.setattr(rag_embedder, "get_embedder", lambda: _FakeEmbedder())
    monkeypatch.setattr(runner_mod, "_summarize_provider", lambda cfg: _FakeProvider())
    registry = JobRegistry()
    job_id = registry.create(kind="ask")
    runner_mod.run_ask_job(registry, job_id, "wat is het antwoord?", db)
    rec = _wait(registry, job_id)
    assert rec.status == JobStatus.complete
    assert rec.result["answer"].startswith("Het antwoord")
    src = rec.result["sources"][0]
    assert src["transcript_id"] == "alpha"
    assert src["segment_index"] == 0
    assert src["start"] == 12.0


def test_run_ask_job_empty_index_fails_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_embedder, "get_embedder", lambda: _FakeEmbedder())
    empty = LibraryDB(tmp_path / "empty.db")
    registry = JobRegistry()
    job_id = registry.create(kind="ask")
    runner_mod.run_ask_job(registry, job_id, "iets?", empty)
    rec = _wait(registry, job_id)
    assert rec.status == JobStatus.failed
    assert "index" in (rec.error or "").lower()
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/api/test_ask_job.py -v`
Expected: FAIL — no `build_ask_messages` / no `run_ask_job`

- [ ] **Step 3: Implement**

1. `speechtotext/api/jobs.py` — add to `JobRecord` (after `paths`):

```python
    result: dict | None = None
```

2. `speechtotext/api/routes_jobs.py` — in `_job_dict`, add to the returned dict:

```python
        "result": rec.result,
```

3. `speechtotext/summarize/prompt.py` — add:

```python
def build_ask_messages(question: str, chunks: list[dict]) -> list[dict]:
    """RAG prompt: numbered transcript excerpts + the user's question.

    The API returns the source list separately, so [n] citations in the
    answer are cosmetic — nothing parses them.
    """
    lines = []
    for n, c in enumerate(chunks, 1):
        ts = ""
        if c.get("start") is not None:
            ts = f" @ {int(c['start'] // 60)}:{int(c['start'] % 60):02d}"
        lines.append(f"[{n}]{ts} {c['text']}")
    excerpts = "\n\n".join(lines)
    return [
        {"role": "system", "content": (
            "You answer questions about the user's personal transcript "
            "library. Use ONLY the numbered excerpts provided. If they do "
            "not contain the answer, say so plainly. Answer in the language "
            "of the question. Cite excerpt numbers like [2] where relevant."
        )},
        {"role": "user", "content": f"Excerpts:\n\n{excerpts}\n\nQuestion: {question}"},
    ]
```

4. `speechtotext/api/runner.py` — add near `run_summarize_job` (mirror its loop/emit boilerplate exactly; `_make_emit`, own-loop handling and the thread spawn are identical — copy them from `run_summarize_job`, lines 207-270):

```python
ASK_TOP_K = 8


def run_ask_job(
    registry: JobRegistry,
    job_id: str,
    question: str,
    db,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> None:
    """Answer a question over the whole library (RAG).

    Retrieves the top chunks by embedding similarity, asks the configured
    LLM provider, and stores {answer, sources} on the JobRecord.
    """
    from speechtotext.rag import embedder as rag_embedder
    from speechtotext.summarize.prompt import build_ask_messages

    try:
        loop = asyncio.get_running_loop()
        _own_loop = False
    except RuntimeError:
        loop = asyncio.new_event_loop()
        _own_loop = True

    emit = _make_emit(loop, registry, job_id)

    def _work() -> None:
        try:
            emit(StageEvent(stage="retrieve", percent=0.0))
            qvec = rag_embedder.get_embedder().embed([question])[0]
            chunks = db.top_chunks(qvec, rag_embedder.EMBED_MODEL, k=ASK_TOP_K)
            if not chunks:
                emit(ErrorEvent(message=(
                    "nothing retrieved — the semantic index may still be "
                    "building, or the library is empty"
                )))
                return
            emit(StageEvent(stage="ask", percent=0.3))
            cfg = load_config(config_path=config_path)
            provider = _summarize_provider(cfg)
            answer = provider.chat(build_ask_messages(question, chunks))
            registry.get(job_id).result = {
                "answer": answer,
                "sources": [
                    {
                        "transcript_id": c["transcript_id"],
                        "segment_index": c["first_segment"],
                        "start": c["start"],
                    }
                    for c in chunks
                ],
            }
            emit(CompleteEvent())
        except (ProviderError, rag_embedder.EmbedderError) as exc:
            emit(ErrorEvent(message=str(exc)))
        except Exception as exc:  # noqa: BLE001
            emit(ErrorEvent(message=f"{type(exc).__name__}: {exc}"))
        finally:
            if _own_loop:
                loop.close()  # match run_summarize_job's exact finally block

    threading.Thread(target=_work, daemon=True).start()  # match run_summarize_job's exact spawn
```

**Important:** copy the `finally:` block and the thread spawn line verbatim from `run_summarize_job` — the sketch above marks them; the real file may differ slightly (e.g. loop shutdown helper).

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/api/test_ask_job.py tests/api/test_runner.py tests/api/test_jobs.py tests/api/test_routes_jobs.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/jobs.py speechtotext/api/routes_jobs.py speechtotext/summarize/prompt.py speechtotext/api/runner.py tests/api/test_ask_job.py
git commit -m "feat(rag): ask job — retrieve top chunks, LLM answer with sources"
```

---

### Task 9: POST /library/ask endpoint

**Files:**
- Create: `speechtotext/api/routes_ask.py`
- Modify: `speechtotext/api/app.py` (router include, around line 295)
- Test: `tests/api/test_routes_ask.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_routes_ask.py` (same client fixture pattern as Task 6):

```python
from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from speechtotext.api import runner as runner_mod
from speechtotext.api.app import create_app
from speechtotext.rag import embedder as rag_embedder


class _FakeEmbedder:
    def embed(self, texts):
        v = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
        return np.repeat(v, len(texts), axis=0)


class _FakeProvider:
    model = "fake-model"

    def chat(self, messages):
        return "Antwoord."


@pytest.fixture
def client(tmp_path):
    app = create_app(library_dirs=[tmp_path], library_db_path=tmp_path / "lib.db")
    with TestClient(app) as c:
        yield c, app


def test_ask_returns_job_and_result(client, tmp_path, monkeypatch):
    import json
    c, app = client
    monkeypatch.setattr(rag_embedder, "get_embedder", lambda: _FakeEmbedder())
    monkeypatch.setattr(runner_mod, "_summarize_provider", lambda cfg: _FakeProvider())
    doc = {
        "audio_path": "/x/a.mp3",
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "S", "text": "hallo wereld"}],
        "created_at": "2026-07-18T12:00:00+00:00",
    }
    p = tmp_path / "alpha.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    db = app.state.library_db
    db.upsert_path(p)
    vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    pend = db.pending_chunks(rag_embedder.EMBED_MODEL, limit=10)
    db.store_embeddings(rag_embedder.EMBED_MODEL, 3, [(cid, vec.tobytes()) for cid, _ in pend])

    r = c.post("/library/ask", json={"question": "wat?"})
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    import time
    for _ in range(100):
        rec = c.get(f"/jobs/{job_id}").json()
        if rec["status"] in ("complete", "failed"):
            break
        time.sleep(0.05)
    assert rec["status"] == "complete"
    assert rec["result"]["answer"] == "Antwoord."
    assert rec["result"]["sources"][0]["transcript_id"] == "alpha"


def test_ask_validates_question(client):
    c, _ = client
    assert c.post("/library/ask", json={"question": ""}).status_code == 422
    assert c.post("/library/ask", json={}).status_code == 422
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/api/test_routes_ask.py -v`
Expected: FAIL with 404 on `/library/ask`

- [ ] **Step 3: Implement route + register**

Create `speechtotext/api/routes_ask.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter()


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@router.post("/library/ask", status_code=202)
def post_ask(body: AskBody, request: Request) -> dict:
    from speechtotext.api import runner  # lazy, matches routes_summarize pattern

    registry = request.app.state.jobs
    job_id = registry.create(kind="ask", audio_path=None)
    runner.run_ask_job(registry, job_id, body.question, request.app.state.library_db)
    return {"job_id": job_id}
```

In `speechtotext/api/app.py`: import the router alongside the others (mirror how `routes_summarize` is imported/included — search for `summarize_router` or its include call) and add `app.include_router(ask_router)` next to it.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/api/test_routes_ask.py tests/api/test_app.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/routes_ask.py speechtotext/api/app.py tests/api/test_routes_ask.py
git commit -m "feat(api): POST /library/ask — library-wide RAG question job"
```

---

### Task 10: UI — Ask panel

**Files:**
- Modify: `ui/src/api/types.ts` (JobRecord.result, AskSource)
- Create: `ui/src/screens/AskPanel.tsx`
- Modify: `ui/src/screens/LibraryScreen.tsx` (render panel)
- Modify: `ui/src/styles/global.css` (minimal panel styles)
- Test: `ui/src/screens/AskPanel.test.tsx`

- [ ] **Step 1: Types**

In `ui/src/api/types.ts`, add and extend:

```ts
export interface AskSource {
  transcript_id: string;
  segment_index: number;
  start: number | null;
}

export interface AskResult {
  answer: string;
  sources: AskSource[];
}
```

and add to `JobRecord`: `result?: AskResult | null;`

- [ ] **Step 2: Write the failing component test**

Create `ui/src/screens/AskPanel.test.tsx` (mirror mock/setup conventions from `LibraryScreen.test.tsx` — read it first; especially how `api` is mocked and how stores are reset):

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import { AskPanel } from './AskPanel';

vi.mock('../api/client', () => ({ api: vi.fn() }));

describe('AskPanel', () => {
  it('submits a question, polls the job, renders answer and sources', async () => {
    vi.mocked(api)
      .mockResolvedValueOnce({ job_id: 'j1' }) // POST /library/ask
      .mockResolvedValueOnce({
        id: 'j1', status: 'complete',
        result: {
          answer: 'Het antwoord is 42.',
          sources: [{ transcript_id: 't1', segment_index: 3, start: 61 }],
        },
      });
    render(<AskPanel setRoute={() => {}} setTid={() => {}} pollMs={1} />);
    await userEvent.type(screen.getByPlaceholderText(/ask your library/i), 'wat is het antwoord?');
    await userEvent.click(screen.getByRole('button', { name: /ask/i }));
    await waitFor(() => expect(screen.getByText('Het antwoord is 42.')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /1:01/ })).toBeInTheDocument();
  });

  it('shows the job error on failure', async () => {
    vi.mocked(api)
      .mockResolvedValueOnce({ job_id: 'j1' })
      .mockResolvedValueOnce({ id: 'j1', status: 'failed', error: 'no provider' });
    render(<AskPanel setRoute={() => {}} setTid={() => {}} pollMs={1} />);
    await userEvent.type(screen.getByPlaceholderText(/ask your library/i), 'x');
    await userEvent.click(screen.getByRole('button', { name: /ask/i }));
    await waitFor(() => expect(screen.getByText(/no provider/)).toBeInTheDocument());
  });
});
```

- [ ] **Step 3: Run to verify fail**

Run: `cd ui && npx vitest run src/screens/AskPanel.test.tsx`
Expected: FAIL — module `./AskPanel` not found

- [ ] **Step 4: Implement AskPanel**

Create `ui/src/screens/AskPanel.tsx`:

```tsx
import { useState } from 'react';
import { api } from '../api/client';
import type { AskResult, JobRecord } from '../api/types';
import { useTranscripts } from '../stores/transcripts';
import { usePendingFind } from '../stores/pendingFind';
import type { Route } from '../types/route';

interface Props {
  setRoute: (r: Route) => void;
  setTid: (id: string) => void;
  pollMs?: number;
}

function fmtTs(secs: number) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

export function AskPanel({ setRoute, setTid, pollMs = 1500 }: Props) {
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AskResult | null>(null);
  const load = useTranscripts(s => s.load);

  const ask = async () => {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true); setError(null); setResult(null);
    try {
      const { job_id } = await api<{ job_id: string }>('/library/ask', {
        method: 'POST',
        body: JSON.stringify({ question: q }),
        headers: { 'Content-Type': 'application/json' },
      });
      for (;;) {
        const rec = await api<JobRecord>(`/jobs/${job_id}`);
        if (rec.status === 'complete') { setResult(rec.result ?? null); break; }
        if (rec.status === 'failed') { setError(rec.error ?? 'ask failed'); break; }
        await new Promise(r => setTimeout(r, pollMs));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ask-panel">
      <div className="ask-input">
        <input
          value={question}
          onChange={e => setQuestion(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') void ask(); }}
          placeholder="Ask your library — e.g. “what did we agree about the deadline?”"
        />
        <button onClick={() => void ask()} disabled={busy || !question.trim()}>
          {busy ? 'Asking…' : 'Ask'}
        </button>
      </div>
      {error && <div className="ask-error">{error}</div>}
      {result && (
        <div className="ask-result">
          <p className="ask-answer">{result.answer}</p>
          <div className="ask-sources">
            {result.sources.map((s, i) => (
              <button
                key={i}
                className="lib-hit"
                onClick={async () => {
                  usePendingFind.getState().set({
                    tid: s.transcript_id,
                    query: '',            // no lexical query: falls back to segment scroll
                    fuzzy: false,
                    segmentIndex: s.segment_index,
                  });
                  try { await load(s.transcript_id); setTid(s.transcript_id); setRoute('complete'); } catch {}
                }}
              >
                {s.start != null ? fmtTs(s.start) : `#${i + 1}`}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

(Check `api()`'s actual signature in `ui/src/api/client.ts` before writing the POST — if it already JSON-encodes a `body` option or sets headers, follow its conventions like `stores/transcripts.ts` does.)

- [ ] **Step 5: Render in LibraryScreen + styles**

In `LibraryScreen.tsx`: `import { AskPanel } from './AskPanel';` and render `<AskPanel setRoute={setRoute} setTid={setTid} />` directly under the `.lib-search` div.

In `ui/src/styles/global.css`, add (match surrounding variable usage — check how `.lib-search` styles its input/buttons and reuse those variables):

```css
.ask-panel { margin: 8px 0 12px; }
.ask-input { display: flex; gap: 8px; }
.ask-input input { flex: 1; }
.ask-error { color: var(--danger, #c00); margin-top: 6px; }
.ask-answer { white-space: pre-wrap; margin: 10px 0 6px; }
.ask-sources { display: flex; gap: 6px; flex-wrap: wrap; }
```

Note the memory rule: full-width, wrapping text — `.ask-answer` must wrap, never ellipsize.

- [ ] **Step 6: Run UI tests**

Run: `cd ui && npx vitest run src/screens/AskPanel.test.tsx src/screens/LibraryScreen.test.tsx`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add ui/src/api/types.ts ui/src/screens/AskPanel.tsx ui/src/screens/LibraryScreen.tsx ui/src/styles/global.css ui/src/screens/AskPanel.test.tsx
git commit -m "feat(ui): Ask your library panel with jump-to-segment sources"
```

---

### Task 11: Full verification

- [ ] **Step 1: Full Python suite**

Run: `cd /Users/lieuwejongsma/SpeechToText && python -m pytest tests/ -x -q`
Expected: all pass (pre-existing dirty-worktree test files `tests/api/test_library_dirs_persistence.py` / `test_webui_serving.py` were already modified before this work — leave their state as found)

- [ ] **Step 2: Full UI suite + typecheck**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: pass

- [ ] **Step 3: Manual smoke (device-test batch per user preference)**

Defer live checks to the user's batched manual session, but note what to verify:
1. Start sidecar with a real library → embed worker backfills (watch log lines).
2. Toggle "≈ meaning" and search a paraphrase → hits appear, jump works.
3. Ask a question with Ollama/LM Studio running → answer + clickable sources.
4. Stop the provider → Ask shows the error; semantic search still works.

- [ ] **Step 4: Version bump + commit**

Bump `version` in `pyproject.toml` (0.16.0 → 0.17.0, minor: new feature) and the UI version if `ui/package.json` tracks one (follow the repo's prior bump commits, e.g. `3ef4190`).

```bash
git add pyproject.toml ui/package.json
git commit -m "chore: bump to v0.17.0 (RAG: semantic search + library Q&A)"
```
