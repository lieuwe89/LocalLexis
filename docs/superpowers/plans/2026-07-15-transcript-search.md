# Transcript Search (Segment Hits + PDF-Style Find + Fuzzy) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Library search returns per-segment hits (click → open transcript at that line), in-transcript find gains a fuzzy toggle and per-occurrence stepping, and both search surfaces support phonetic + typo matching with relevance/date sorting.

**Architecture:** Backend adds two per-segment FTS5 tables (exact text + Double Metaphone codes) to the throwaway SQLite index; `GET /transcripts` returns `hits[]` per transcript with `fuzzy`/`sort` params. Frontend adds a shared TS matching util, a `pendingFind` zustand store to hand off "jump to segment" between screens, and upgrades to LibraryScreen/CompleteScreen. Spec: `docs/superpowers/specs/2026-07-15-transcript-search-design.md`.

**Tech Stack:** Python 3 / FastAPI / SQLite FTS5, pip `Metaphone` (pure-Python doublemetaphone); React 19 + Zustand 5 + Vite, npm `double-metaphone`; pytest + Vitest.

**Conventions that bite:**
- Run Python tests with `.venv/bin/python -m pytest` from repo root — system python segfaults importing ctranslate2.
- Run UI tests with `cd ui && npx vitest run <file>`.
- FTS5 `bm25()` returns *lower = better*; all ranking sorts ascending.
- Snippets are structured `{text, match}` parts split on private-use sentinels — never HTML.

---

### Task 1: Python phonetic encoder (`phonetics.py`)

**Files:**
- Create: `speechtotext/api/phonetics.py`
- Test: `tests/api/test_phonetics.py`
- Modify: `pyproject.toml` (add `Metaphone` to `api` extras), `requirements-server-cpu.txt`

- [ ] **Step 1: Install the dependency**

```bash
.venv/bin/pip install "Metaphone>=0.6"
```

Add to `pyproject.toml` under `[project.optional-dependencies]` → `api = [` list (alphabetical position fine):

```toml
    "Metaphone>=0.6",
```

Add the same line `Metaphone>=0.6` to `requirements-server-cpu.txt` (keep the file's existing ordering style).

- [ ] **Step 2: Write the failing test**

Create `tests/api/test_phonetics.py`:

```python
"""Tests for the Double Metaphone token/text encoder used by fuzzy search."""

from __future__ import annotations

from speechtotext.api.phonetics import WORD_RE, encode_text, encode_token


def test_phonetic_pairs_share_code():
    # Classic ASR-mishearing pair: same pronunciation, different spelling.
    assert encode_token("Kaitlyn") == encode_token("Catelin")


def test_different_words_get_different_codes():
    assert encode_token("meeting") != encode_token("budget")


def test_unencodable_tokens_pass_through_lowercased():
    assert encode_token("2024") == "2024"
    assert encode_token("§§") == "§§"


def test_encode_text_replaces_each_word_with_its_code():
    out = encode_text("Hello world 42")
    assert out.split() == [encode_token("Hello"), encode_token("world"), "42"]


def test_encode_text_token_positions_align_with_word_re():
    # The snippet builder relies on 1:1 alignment between WORD_RE tokens
    # of the original text and the space-separated codes.
    text = "Well, Kaitlyn said: budget!"
    words = [m.group(0) for m in WORD_RE.finditer(text)]
    codes = encode_text(text).split()
    assert len(words) == len(codes)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_phonetics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'speechtotext.api.phonetics'`

- [ ] **Step 4: Write the implementation**

Create `speechtotext/api/phonetics.py`:

```python
"""Double Metaphone encoding for fuzzy (phonetic) library search.

Segment text is indexed twice: verbatim (segments_fts) and with every word
replaced by its Double Metaphone primary code (segments_phonetic). A fuzzy
query encodes its tokens the same way, so "Catelin" matches "Kaitlyn".

The Python encoder and the frontend's npm `double-metaphone` never
cross-compare: the library path encodes query and index both server-side,
the in-transcript find encodes both client-side.
"""

from __future__ import annotations

import re

from metaphone import doublemetaphone

# Word tokenizer shared by the indexer and the phonetic snippet builder.
# Letters and digits only (no underscore), unicode-aware.
WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


def encode_token(token: str) -> str:
    """Primary Double Metaphone code for one token.

    Tokens that produce no code (numbers, symbols) are returned lowercased
    verbatim so they still match exactly inside a phonetic query.
    """
    primary = doublemetaphone(token)[0]
    return primary if primary else token.lower()


def encode_text(text: str) -> str:
    """Replace each word in ``text`` with its phonetic code, space-joined.

    Token positions align 1:1 with WORD_RE matches over the original text;
    the snippet builder depends on that alignment.
    """
    return " ".join(encode_token(m.group(0)) for m in WORD_RE.finditer(text))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/api/test_phonetics.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add speechtotext/api/phonetics.py tests/api/test_phonetics.py pyproject.toml requirements-server-cpu.txt
git commit -m "feat(api): Double Metaphone encoder for fuzzy search"
```

---

### Task 2: Schema v2 — per-segment FTS tables + indexing

**Files:**
- Modify: `speechtotext/api/library_db.py` (DDL at :59-123, `SCHEMA_VERSION` at :35, `_migrate` at :238, `upsert_path` at :273, `_upsert_error` at :365, `delete_by_path` at :390)
- Test: `tests/api/test_library_db_segments.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_library_db_segments.py` (helpers copied from `tests/api/test_library_db.py` so this file stands alone):

```python
"""Tests for per-segment FTS indexing and schema v2 migration."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from speechtotext.api.library_db import SCHEMA_VERSION, LibraryDB


def _make_doc(text_segments: list[tuple[float, float, str, str]],
              audio_name: str = "meeting.mp3") -> dict:
    return {
        "version": 1,
        "audio_path": f"/some/dir/{audio_name}",
        "duration_seconds": text_segments[-1][1] if text_segments else 0.0,
        "language": "en",
        "speakers": {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"},
        "segments": [
            {"start": s, "end": e, "speaker": sp, "text": t}
            for s, e, sp, t in text_segments
        ],
        "models": {"asr": "faster-whisper:base.en"},
        "created_at": "2026-05-17T12:00:00+00:00",
    }


def _write(dir: Path, name: str, doc: dict) -> Path:
    p = dir / f"{name}.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


@pytest.fixture
def db(tmp_path: Path) -> LibraryDB:
    return LibraryDB(tmp_path / "library.db")


def _seg_rows(db: LibraryDB, table: str, tid: str) -> list[sqlite3.Row]:
    return db._conn.execute(
        f"SELECT * FROM {table} WHERE transcript_id=? ORDER BY segment_index",
        (tid,),
    ).fetchall()


def test_upsert_indexes_each_segment(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "alpha", _make_doc([
        (0.0, 2.0, "SPEAKER_00", "hello world"),
        (2.0, 4.0, "SPEAKER_01", "goodbye moon"),
    ]))
    db.upsert_path(p)
    rows = _seg_rows(db, "segments_fts", "alpha")
    assert [(r["segment_index"], r["text"], r["start"]) for r in rows] == [
        (0, "hello world", 0.0),
        (1, "goodbye moon", 2.0),
    ]
    ph = _seg_rows(db, "segments_phonetic", "alpha")
    assert len(ph) == 2
    assert ph[0]["text"] == "hello world"  # original text stored for snippets


def test_empty_segments_are_skipped(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "a", _make_doc([
        (0.0, 1.0, "SPEAKER_00", "real text"),
        (1.0, 2.0, "SPEAKER_00", "   "),
    ]))
    db.upsert_path(p)
    assert len(_seg_rows(db, "segments_fts", "a")) == 1


def test_reupsert_replaces_segment_rows(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "a", _make_doc([(0.0, 1.0, "SPEAKER_00", "one"),
                                         (1.0, 2.0, "SPEAKER_00", "two")]))
    db.upsert_path(p)
    _write(tmp_path, "a", _make_doc([(0.0, 1.0, "SPEAKER_00", "only")]))
    db.upsert_path(p)
    rows = _seg_rows(db, "segments_fts", "a")
    assert [(r["segment_index"], r["text"]) for r in rows] == [(0, "only")]
    assert len(_seg_rows(db, "segments_phonetic", "a")) == 1


def test_delete_removes_segment_rows(db: LibraryDB, tmp_path: Path):
    p = _write(tmp_path, "a", _make_doc([(0.0, 1.0, "SPEAKER_00", "hello")]))
    db.upsert_path(p)
    db.delete_by_path(p)
    assert _seg_rows(db, "segments_fts", "a") == []
    assert _seg_rows(db, "segments_phonetic", "a") == []


def test_version_mismatch_drops_and_rebuilds(tmp_path: Path):
    db_path = tmp_path / "library.db"
    db = LibraryDB(db_path)
    p = _write(tmp_path, "a", _make_doc([(0.0, 1.0, "SPEAKER_00", "hello")]))
    db.upsert_path(p)
    # Simulate an old-schema DB by forging a stale version number.
    db._conn.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION - 1,))
    db._conn.commit()
    db.close()

    db2 = LibraryDB(db_path)  # must not raise; must start empty
    assert db2.list() == []
    row = db2._conn.execute("SELECT version FROM schema_version").fetchone()
    assert row[0] == SCHEMA_VERSION
    # And reindexing works on the fresh schema.
    db2.upsert_path(p)
    assert len(db2.list()) == 1
    db2.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/api/test_library_db_segments.py -v`
Expected: FAIL with `sqlite3.OperationalError: no such table: segments_fts` (and ImportError-free)

- [ ] **Step 3: Implement schema + indexing**

In `speechtotext/api/library_db.py`:

**(a)** Change `SCHEMA_VERSION = 1` → `SCHEMA_VERSION = 2`.

**(b)** Add import at top (after the existing imports):

```python
from speechtotext.api.phonetics import encode_text
```

**(c)** Append two DDL entries to the `_DDL` list (after the `transcripts_fts` entry, before the RAG comment):

```python
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
        text,
        transcript_id UNINDEXED,
        segment_index UNINDEXED,
        start UNINDEXED,
        tokenize='porter unicode61 remove_diacritics 2'
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS segments_phonetic USING fts5(
        codes,
        text UNINDEXED,
        transcript_id UNINDEXED,
        segment_index UNINDEXED,
        start UNINDEXED,
        tokenize='unicode61'
    )
    """,
```

**(d)** Replace the body of `_migrate` (keep the two trailing ALTER blocks for `origin` and `title` unchanged):

```python
    def _migrate(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version "
                "(version INTEGER NOT NULL PRIMARY KEY)"
            )
            row = self._conn.execute(
                "SELECT version FROM schema_version LIMIT 1"
            ).fetchone()
            if row is not None and row[0] != SCHEMA_VERSION:
                # The DB is a throwaway index over the JSON sidecars: on any
                # version mismatch, drop everything and let the next
                # reconcile rebuild from disk.
                for tbl in (
                    "transcripts_fts", "segments_fts", "segments_phonetic",
                    "embeddings", "chunks", "transcripts", "schema_version",
                ):
                    self._conn.execute(f"DROP TABLE IF EXISTS {tbl}")
                self._conn.execute(
                    "CREATE TABLE IF NOT EXISTS schema_version "
                    "(version INTEGER NOT NULL PRIMARY KEY)"
                )
                row = None
            for stmt in _DDL:
                self._conn.execute(stmt)
            if row is None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                    (SCHEMA_VERSION,),
                )
```

**(e)** In `upsert_path`, inside the `with self._lock, self._conn:` block, after the `INSERT INTO transcripts_fts (...)` execute, add:

```python
            self._conn.execute(
                "DELETE FROM segments_fts WHERE transcript_id=?", (tid,)
            )
            self._conn.execute(
                "DELETE FROM segments_phonetic WHERE transcript_id=?", (tid,)
            )
            for idx, seg in enumerate(doc.get("segments") or []):
                text = str(seg.get("text") or "")
                if not text.strip():
                    continue
                start = seg.get("start")
                self._conn.execute(
                    "INSERT INTO segments_fts "
                    "(text, transcript_id, segment_index, start) "
                    "VALUES (?, ?, ?, ?)",
                    (text, tid, idx, start),
                )
                self._conn.execute(
                    "INSERT INTO segments_phonetic "
                    "(codes, text, transcript_id, segment_index, start) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (encode_text(text), text, tid, idx, start),
                )
```

**(f)** In `_upsert_error`, after the `DELETE FROM transcripts_fts` execute, add:

```python
            self._conn.execute(
                "DELETE FROM segments_fts WHERE transcript_id=?", (tid,)
            )
            self._conn.execute(
                "DELETE FROM segments_phonetic WHERE transcript_id=?", (tid,)
            )
```

**(g)** In `delete_by_path`, change the initial SELECT to also fetch the id, and delete segment rows:

```python
    def delete_by_path(self, json_path: Path) -> None:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT rowid, id FROM transcripts WHERE json_path=?",
                (str(json_path),),
            ).fetchone()
            if row is None:
                return
            self._conn.execute(
                "DELETE FROM transcripts_fts WHERE rowid=?", (row["rowid"],)
            )
            self._conn.execute(
                "DELETE FROM segments_fts WHERE transcript_id=?", (row["id"],)
            )
            self._conn.execute(
                "DELETE FROM segments_phonetic WHERE transcript_id=?", (row["id"],)
            )
            self._conn.execute(
                "DELETE FROM transcripts WHERE rowid=?", (row["rowid"],)
            )
```

- [ ] **Step 4: Run tests to verify they pass, plus the existing library suite**

Run: `.venv/bin/python -m pytest tests/api/test_library_db_segments.py tests/api/test_library_db.py tests/api/test_library_db_origin.py tests/api/test_library_title.py tests/api/test_reconcile.py -v`
Expected: all PASS (existing tests unaffected — v2 tables are additive; fresh test DBs get version 2 directly)

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/library_db.py tests/api/test_library_db_segments.py
git commit -m "feat(api): schema v2 — per-segment exact + phonetic FTS tables"
```

---

### Task 3: `LibraryDB.search()` — segment hits, fuzzy, sort

**Files:**
- Modify: `speechtotext/api/library_db.py` (`search` at :479, module top for constants + `_phonetic_snippet`)
- Test: `tests/api/test_library_db_search_hits.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_library_db_search_hits.py`:

```python
"""Tests for segment-level search hits, fuzzy matching, and sorting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from speechtotext.api.library_db import LibraryDB, _phonetic_snippet
from speechtotext.api.phonetics import encode_token


def _make_doc(text_segments: list[tuple[float, float, str, str]],
              audio_name: str = "meeting.mp3",
              created_at: str = "2026-05-17T12:00:00+00:00") -> dict:
    return {
        "version": 1,
        "audio_path": f"/some/dir/{audio_name}",
        "duration_seconds": text_segments[-1][1] if text_segments else 0.0,
        "language": "en",
        "speakers": {"SPEAKER_00": "Alice"},
        "segments": [
            {"start": s, "end": e, "speaker": sp, "text": t}
            for s, e, sp, t in text_segments
        ],
        "models": {"asr": "faster-whisper:base.en"},
        "created_at": created_at,
    }


def _write(dir: Path, name: str, doc: dict) -> Path:
    p = dir / f"{name}.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


@pytest.fixture
def db(tmp_path: Path) -> LibraryDB:
    return LibraryDB(tmp_path / "library.db")


def test_search_returns_segment_hits(db: LibraryDB, tmp_path: Path):
    db.upsert_path(_write(tmp_path, "a", _make_doc([
        (0.0, 2.0, "SPEAKER_00", "we should review the budget today"),
        (2.0, 4.0, "SPEAKER_00", "lunch plans for tomorrow"),
        (4.0, 6.0, "SPEAKER_00", "back to the budget line items"),
    ])))
    items = db.search("budget")
    assert len(items) == 1
    item = items[0]
    assert item["total_hits"] == 2
    idxs = [h["segment_index"] for h in item["hits"]]
    assert sorted(idxs) == [0, 2]
    h0 = item["hits"][0]
    assert h0["start"] in (0.0, 4.0)
    assert any(p["match"] for p in h0["snippet_parts"])
    # top-level snippet mirrors the best hit for back-compat
    assert item["snippet_parts"] == h0["snippet_parts"]


def test_hits_capped_at_five_with_full_total(db: LibraryDB, tmp_path: Path):
    segs = [(float(i), float(i + 1), "SPEAKER_00", f"budget item {i}")
            for i in range(8)]
    db.upsert_path(_write(tmp_path, "a", _make_doc(segs)))
    item = db.search("budget")[0]
    assert len(item["hits"]) == 5
    assert item["total_hits"] == 8


def test_fuzzy_finds_phonetic_match(db: LibraryDB, tmp_path: Path):
    db.upsert_path(_write(tmp_path, "a", _make_doc([
        (0.0, 2.0, "SPEAKER_00", "then Kaitlyn presented the roadmap"),
    ])))
    assert db.search("Catelin") == [] or not db.search("Catelin")[0].get("hits")
    items = db.search("Catelin", fuzzy=True)
    assert len(items) == 1
    hit = items[0]["hits"][0]
    assert hit["segment_index"] == 0
    marked = [p["text"] for p in hit["snippet_parts"] if p["match"]]
    assert marked == ["Kaitlyn"]


def test_fuzzy_ranks_exact_above_phonetic(db: LibraryDB, tmp_path: Path):
    db.upsert_path(_write(tmp_path, "exact", _make_doc(
        [(0.0, 2.0, "SPEAKER_00", "Catelin joined the call")],
        audio_name="one.mp3")))
    db.upsert_path(_write(tmp_path, "phon", _make_doc(
        [(0.0, 2.0, "SPEAKER_00", "Kaitlyn joined the call")],
        audio_name="two.mp3")))
    items = db.search("Catelin", fuzzy=True)
    assert [i["id"] for i in items] == ["exact", "phon"]


def test_sort_by_date(db: LibraryDB, tmp_path: Path):
    db.upsert_path(_write(tmp_path, "old", _make_doc(
        [(0.0, 2.0, "SPEAKER_00", "budget budget budget")],
        audio_name="old.mp3", created_at="2026-01-01T00:00:00+00:00")))
    db.upsert_path(_write(tmp_path, "new", _make_doc(
        [(0.0, 2.0, "SPEAKER_00", "one budget mention")],
        audio_name="new.mp3", created_at="2026-06-01T00:00:00+00:00")))
    by_rel = db.search("budget")
    assert by_rel[0]["id"] == "old"  # more matches → better bm25
    by_date = db.search("budget", sort="date")
    assert [i["id"] for i in by_date] == ["new", "old"]


def test_filename_only_match_still_returned_without_hits(db: LibraryDB, tmp_path: Path):
    db.upsert_path(_write(tmp_path, "a", _make_doc(
        [(0.0, 2.0, "SPEAKER_00", "unrelated words")],
        audio_name="standup-retro.mp3")))
    items = db.search("standup")
    assert len(items) == 1
    assert "hits" not in items[0]


def test_phonetic_snippet_marks_matching_tokens():
    codes = {encode_token("Kaitlyn")}
    parts = _phonetic_snippet("and then Kaitlyn spoke up", codes)
    marked = [p["text"] for p in parts if p["match"]]
    assert marked == ["Kaitlyn"]
    joined = "".join(p["text"] for p in parts)
    assert "spoke" in joined


def test_phonetic_snippet_windows_long_text():
    filler = " ".join(f"word{i}" for i in range(40))
    text = f"{filler} Kaitlyn closes"
    parts = _phonetic_snippet(text, {encode_token("Kaitlyn")})
    joined = "".join(p["text"] for p in parts)
    assert joined.startswith("…")
    assert "word0 " not in joined
    assert [p["text"] for p in parts if p["match"]] == ["Kaitlyn"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/api/test_library_db_search_hits.py -v`
Expected: FAIL — `ImportError: cannot import name '_phonetic_snippet'` first; after stubbing, hit-shape assertions fail.

- [ ] **Step 3: Implement**

In `speechtotext/api/library_db.py`:

**(a)** Change the phonetics import (from Task 2) to:

```python
from speechtotext.api.phonetics import WORD_RE, encode_text, encode_token
```

**(b)** Add module constants near `SCHEMA_VERSION`:

```python
# Phonetic-only hits always rank below every exact hit; bm25 values are
# small negatives, so a large positive offset guarantees the ordering.
_PHONETIC_RANK_OFFSET = 1000.0
_HITS_PER_TRANSCRIPT = 5
```

**(c)** Add `_phonetic_snippet` after `_parse_snippet`:

```python
def _phonetic_snippet(text: str, query_codes: set[str],
                      context: int = 6, max_tokens: int = 24) -> list[dict]:
    """Build [{text, match}] parts for a phonetic hit.

    FTS5's snippet() can only mark matches in the indexed column — which for
    segments_phonetic holds codes, not words. So we re-encode the original
    text token by token (positions align 1:1 with the codes column by
    construction) and mark tokens whose code is in the query, windowing
    around the first match like snippet() does.
    """
    tokens = [(m.start(), m.end()) for m in WORD_RE.finditer(text)]
    flags = [encode_token(text[a:b]) in query_codes for a, b in tokens]
    if not any(flags):
        return [{"text": text[:200], "match": False}]
    first = flags.index(True)
    lo = max(0, first - context)
    hi = min(len(tokens), lo + max_tokens)
    parts: list[dict] = []

    def emit(t: str, match: bool) -> None:
        if t:
            parts.append({"text": t, "match": match})

    if lo > 0:
        emit("…", False)
    cursor = tokens[lo][0]
    for i in range(lo, hi):
        a, b = tokens[i]
        emit(text[cursor:a], False)
        emit(text[a:b], flags[i])
        cursor = b
    if hi < len(tokens):
        emit("…", False)
    return parts
```

**(d)** Replace `search` entirely:

```python
    def search(self, query: str, limit: int = 50, *,
               fuzzy: bool = False, sort: str = "relevance") -> list[dict]:
        match = _quote_fts(query)
        if not match:
            return self.list(limit=limit)

        # 1) Exact per-segment hits.
        hits: dict[str, dict[int, dict]] = {}
        with self._lock:
            seg_rows = self._conn.execute(
                """
                SELECT transcript_id, segment_index, start,
                       snippet(segments_fts, 0, ?, ?, '…', 24) AS snip,
                       bm25(segments_fts) AS rank
                FROM segments_fts
                WHERE segments_fts MATCH ?
                ORDER BY rank ASC
                LIMIT ?
                """,
                (_SNIPPET_START, _SNIPPET_END, match, limit * 20),
            ).fetchall()
        for r in seg_rows:
            hits.setdefault(r["transcript_id"], {})[r["segment_index"]] = {
                "segment_index": r["segment_index"],
                "start": r["start"],
                "snippet_parts": _parse_snippet(r["snip"]),
                "score": r["rank"],
            }

        # 2) Phonetic per-segment hits (fuzzy mode only). Exact hits on the
        # same segment win; phonetic-only hits rank after all exact hits.
        if fuzzy:
            codes = [encode_token(t) for t in query.split() if t.strip()]
            if codes:
                pmatch = " ".join(
                    '"{}"'.format(c.replace('"', '""')) for c in codes
                )
                with self._lock:
                    ph_rows = self._conn.execute(
                        """
                        SELECT transcript_id, segment_index, start, text,
                               bm25(segments_phonetic) AS rank
                        FROM segments_phonetic
                        WHERE segments_phonetic MATCH ?
                        ORDER BY rank ASC
                        LIMIT ?
                        """,
                        (pmatch, limit * 20),
                    ).fetchall()
                code_set = set(codes)
                for r in ph_rows:
                    tid_hits = hits.setdefault(r["transcript_id"], {})
                    if r["segment_index"] in tid_hits:
                        continue
                    tid_hits[r["segment_index"]] = {
                        "segment_index": r["segment_index"],
                        "start": r["start"],
                        "snippet_parts": _phonetic_snippet(r["text"], code_set),
                        "score": r["rank"] + _PHONETIC_RANK_OFFSET,
                    }

        # 3) Transcript-level matches (filename, speakers, meta + joined
        # content) — keeps title/speaker-only matches in the results.
        with self._lock:
            t_rows = self._conn.execute(
                """
                SELECT t.id, t.json_path, t.audio_path, t.title, t.duration_seconds,
                       t.language, t.speakers_count, t.created_at,
                       t.models_asr, t.models_diarizer, t.error, t.origin,
                       snippet(transcripts_fts, 0, ?, ?, '…', 24) AS snippet,
                       bm25(transcripts_fts, 4.0, 6.0, 3.0, 2.0) AS rank
                FROM transcripts_fts
                JOIN transcripts t ON t.rowid = transcripts_fts.rowid
                WHERE transcripts_fts MATCH ?
                ORDER BY rank ASC
                LIMIT ?
                """,
                (_SNIPPET_START, _SNIPPET_END, match, limit),
            ).fetchall()
        items_by_id: dict[str, dict] = {}
        rank_by_id: dict[str, float] = {}
        for r in t_rows:
            item = self._row_to_item(r)
            item["snippet_parts"] = _parse_snippet(r["snippet"])
            items_by_id[r["id"]] = item
            rank_by_id[r["id"]] = r["rank"]

        # 4) Transcripts reached only via segment hits (e.g. phonetic-only).
        missing = [tid for tid in hits if tid not in items_by_id]
        if missing:
            qmarks = ",".join("?" for _ in missing)
            with self._lock:
                rows = self._conn.execute(
                    f"""
                    SELECT id, json_path, audio_path, title, duration_seconds,
                           language, speakers_count, created_at,
                           models_asr, models_diarizer, error, origin
                    FROM transcripts WHERE id IN ({qmarks})
                    """,
                    missing,
                ).fetchall()
            for r in rows:
                items_by_id[r["id"]] = self._row_to_item(r)

        # 5) Attach hits; the best segment drives the transcript's rank and
        # its top-level snippet (back-compat for clients that ignore hits).
        for tid, seg_hits in hits.items():
            item = items_by_id.get(tid)
            if item is None:
                continue  # row vanished between queries
            ordered = sorted(seg_hits.values(), key=lambda h: h["score"])
            item["hits"] = ordered[:_HITS_PER_TRANSCRIPT]
            item["total_hits"] = len(ordered)
            item["snippet_parts"] = ordered[0]["snippet_parts"]
            best = ordered[0]["score"]
            rank_by_id[tid] = min(rank_by_id.get(tid, best), best)

        items = list(items_by_id.values())
        if sort == "date":
            items.sort(key=lambda i: i.get("created_at") or "", reverse=True)
        else:
            items.sort(key=lambda i: rank_by_id.get(i["id"], 0.0))
        return items[:limit]
```

- [ ] **Step 4: Run tests to verify they pass, plus existing search tests**

Run: `.venv/bin/python -m pytest tests/api/test_library_db_search_hits.py tests/api/test_library_db.py -v`
Expected: all PASS. If an existing `test_library_db.py` search test asserts an exact `snippet_parts` value that now comes from `segments_fts` instead of `transcripts_fts`, update that assertion to check `any(p["match"] ...)` rather than exact text — note the change in the commit message.

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/library_db.py tests/api/test_library_db_search_hits.py tests/api/test_library_db.py
git commit -m "feat(api): segment-level search hits with fuzzy phonetic mode and sort"
```

---

### Task 4: API route params (`fuzzy`, `sort`)

**Files:**
- Modify: `speechtotext/api/routes_transcripts.py:119-134`
- Test: append to `tests/api/test_routes_transcripts.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/api/test_routes_transcripts.py` (reuses its `app_with_lib` fixture at :60):

```python
def test_search_returns_segment_hits(app_with_lib, tmp_path):
    client = TestClient(app_with_lib)
    r = client.get("/transcripts", params={"q": "hi"})
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["hits"][0]["segment_index"] == 0
    assert items[0]["total_hits"] == 1


def test_search_fuzzy_param(app_with_lib):
    client = TestClient(app_with_lib)
    # "hy" is phonetically "hi" (both encode to H); exact search misses it.
    exact = client.get("/transcripts", params={"q": "hy"}).json()
    fuzzy = client.get("/transcripts", params={"q": "hy", "fuzzy": 1}).json()
    assert exact == [] or not any(i.get("hits") for i in exact)
    assert len(fuzzy) == 1 and fuzzy[0]["hits"][0]["segment_index"] == 0


def test_search_sort_param_validation(app_with_lib):
    client = TestClient(app_with_lib)
    assert client.get("/transcripts", params={"q": "hi", "sort": "date"}).status_code == 200
    assert client.get("/transcripts", params={"q": "hi", "sort": "bogus"}).status_code == 422
```

Note: if the "hy"→"hi" phonetic assumption fails (Double Metaphone gives different codes), change the fixture-agnostic pair — use query `"hii"` won't work either; instead extend the `app_with_lib` sample segment text to `"hi Kaitlyn"` and query `"Catelin"`, which is verified in Task 1's tests.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/api/test_routes_transcripts.py -v -k "fuzzy or hits or sort_param"`
Expected: FAIL — `hits` key absent; `fuzzy`/`sort` params ignored (bogus sort returns 200, not 422)

- [ ] **Step 3: Implement**

In `routes_transcripts.py`, replace the `list_transcripts` signature and search call:

```python
@router.get("/transcripts")
def list_transcripts(
    request: Request,
    q: str | None = Query(default=None, description="full-text search query"),
    limit: int = Query(default=200, ge=1, le=1000),
    fuzzy: bool = Query(default=False, description="also match phonetically"),
    sort: str = Query(default="relevance", pattern="^(relevance|date)$"),
) -> list[dict]:
    db = request.app.state.library_db
    # Reconcile before responding so the user sees rows matching disk. The
    # reconciler skips the walk when no library dir's mtime changed, so
    # search-as-you-type doesn't stat every file on every keystroke.
    # Snapshot the dir set (atomic C-level copy) so a background .add() from
    # _on_complete_dir can't grow it mid-iteration inside reconcile.
    request.app.state.library_reconciler.reconcile(set(request.app.state.library_dirs))
    if q:
        return db.search(q, limit=limit, fuzzy=fuzzy, sort=sort)
    return db.list(limit=limit)
```

- [ ] **Step 4: Run the full API test file**

Run: `.venv/bin/python -m pytest tests/api/test_routes_transcripts.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/routes_transcripts.py tests/api/test_routes_transcripts.py
git commit -m "feat(api): fuzzy and sort params on GET /transcripts"
```

---

### Task 5: UI types + library store (fuzzy/sort state)

**Files:**
- Modify: `ui/src/api/types.ts:21-40`, `ui/src/stores/library.ts`
- Test: `ui/src/stores/library.test.ts` (new)

- [ ] **Step 1: Add types**

In `ui/src/api/types.ts`, add after `TranscriptListItem`'s `snippet_parts` doc-comment block, inside the interface:

```ts
  /** Per-segment search hits (only set on search results, schema v2 server). */
  hits?: SegmentHit[];
  /** Total matching segments (hits[] is capped server-side). */
  total_hits?: number;
```

And add above `TranscriptListItem`:

```ts
export interface SegmentHit {
  segment_index: number;
  /** Segment start time in seconds; null for legacy rows. */
  start?: number | null;
  snippet_parts: { text: string; match: boolean }[];
  score: number;
}
```

- [ ] **Step 2: Write the failing store test**

Create `ui/src/stores/library.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest';

const apiMock = vi.fn();
vi.mock('../api/client', () => ({ api: (...args: unknown[]) => apiMock(...args) }));

import { useLibrary } from './library';

describe('useLibrary search params', () => {
  beforeEach(() => {
    apiMock.mockReset();
    apiMock.mockResolvedValue([]);
    useLibrary.setState({ items: [], all: [], query: '', searching: false, fuzzy: false, sort: 'relevance' });
  });

  it('passes fuzzy and sort as query params', async () => {
    useLibrary.setState({ fuzzy: true, sort: 'date' });
    await useLibrary.getState().search('hello world');
    expect(apiMock).toHaveBeenCalledWith('/transcripts?q=hello%20world&fuzzy=1&sort=date');
  });

  it('omits default params', async () => {
    await useLibrary.getState().search('hello');
    expect(apiMock).toHaveBeenCalledWith('/transcripts?q=hello');
  });

  it('setFuzzy re-runs the active search', async () => {
    await useLibrary.getState().search('hello');
    apiMock.mockClear();
    useLibrary.getState().setFuzzy(true);
    await vi.waitFor(() => expect(apiMock).toHaveBeenCalledWith('/transcripts?q=hello&fuzzy=1'));
  });

  it('setSort with no active query does not call the api', () => {
    useLibrary.getState().setSort('date');
    expect(apiMock).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd ui && npx vitest run src/stores/library.test.ts`
Expected: FAIL — `fuzzy`/`setFuzzy` missing from store; URL lacks params

- [ ] **Step 4: Implement the store changes**

Replace `ui/src/stores/library.ts` content:

```ts
import { create } from 'zustand';
import { api } from '../api/client';
import type { TranscriptListItem } from '../api/types';

interface State {
  /** Most recently returned listing — what the UI renders right now. */
  items: TranscriptListItem[];
  /** Full unfiltered list, used by sidebars and the "recent" carousel
   *  so they don't go empty while the user is typing a search. */
  all: TranscriptListItem[];
  query: string;
  searching: boolean;
  /** Phonetic + typo matching for searches. */
  fuzzy: boolean;
  /** Result ordering while a query is active. */
  sort: 'relevance' | 'date';
  refresh: () => Promise<void>;
  search: (q: string) => Promise<void>;
  setFuzzy: (f: boolean) => void;
  setSort: (s: 'relevance' | 'date') => void;
  remove: (id: string) => Promise<void>;
}

export const useLibrary = create<State>((set, get) => ({
  items: [],
  all: [],
  query: '',
  searching: false,
  fuzzy: false,
  sort: 'relevance',
  refresh: async () => {
    const rows = await api<TranscriptListItem[]>('/transcripts');
    set({ all: rows });
    if (!get().query) set({ items: rows });
  },
  search: async (q: string) => {
    set({ query: q });
    const trimmed = q.trim();
    if (!trimmed) {
      set({ items: get().all, searching: false });
      return;
    }
    set({ searching: true });
    const { fuzzy, sort } = get();
    let url = `/transcripts?q=${encodeURIComponent(trimmed)}`;
    if (fuzzy) url += '&fuzzy=1';
    if (sort !== 'relevance') url += `&sort=${sort}`;
    try {
      const rows = await api<TranscriptListItem[]>(url);
      // Guard against a stale response winning over a newer query
      if (get().query === q) set({ items: rows, searching: false });
    } catch {
      if (get().query === q) set({ searching: false });
    }
  },
  setFuzzy: (f: boolean) => {
    set({ fuzzy: f });
    const q = get().query;
    if (q.trim()) void get().search(q);
  },
  setSort: (s: 'relevance' | 'date') => {
    set({ sort: s });
    const q = get().query;
    if (q.trim()) void get().search(q);
  },
  remove: async (id: string) => {
    await api(`/transcripts/${id}`, { method: 'DELETE' });
    await get().refresh();
  },
}));
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd ui && npx vitest run src/stores/library.test.ts`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add ui/src/api/types.ts ui/src/stores/library.ts ui/src/stores/library.test.ts
git commit -m "feat(ui): library store fuzzy/sort search params + SegmentHit type"
```

---

### Task 6: `fuzzyMatch.ts` — shared matching util

**Files:**
- Create: `ui/src/lib/fuzzyMatch.ts`
- Test: `ui/src/lib/fuzzyMatch.test.ts`

- [ ] **Step 1: Install the dependency**

```bash
cd ui && npm install double-metaphone
```

(`double-metaphone` is pure-ESM, no types package needed — it ships its own.)

- [ ] **Step 2: Write the failing tests**

Create `ui/src/lib/fuzzyMatch.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { findMatches } from './fuzzyMatch';

const segs = (...texts: string[]) => texts.map(text => ({ text }));

describe('findMatches exact mode', () => {
  it('finds every occurrence with char ranges', () => {
    const m = findMatches(segs('the cat sat on the cat mat'), 'cat', false);
    expect(m).toEqual([
      { segmentIndex: 0, start: 4, end: 7 },
      { segmentIndex: 0, start: 19, end: 22 },
    ]);
  });

  it('is case-insensitive and spans segments', () => {
    const m = findMatches(segs('Budget review', 'no match', 'BUDGET!'), 'budget', false);
    expect(m.map(x => x.segmentIndex)).toEqual([0, 2]);
  });

  it('returns [] for empty query', () => {
    expect(findMatches(segs('anything'), '  ', false)).toEqual([]);
  });
});

describe('findMatches fuzzy mode', () => {
  it('matches phonetically equivalent words', () => {
    const m = findMatches(segs('then Kaitlyn presented'), 'Catelin', true);
    expect(m).toHaveLength(1);
    const seg = 'then Kaitlyn presented';
    expect(seg.slice(m[0].start, m[0].end)).toBe('Kaitlyn');
  });

  it('matches single-letter typos in words of 5+ chars', () => {
    const m = findMatches(segs('quarterly budgett review'), 'budget', true);
    expect(m).toHaveLength(1);
  });

  it('does not typo-match short words', () => {
    expect(findMatches(segs('the cot sat'), 'cat', true).length)
      .toBeLessThanOrEqual(findMatches(segs('the cat sat'), 'cat', true).length);
    // 'car' vs 'cat': 3 chars, different metaphone codes → no match
    expect(findMatches(segs('nice car'), 'cat', true)).toEqual([]);
  });

  it('matches multi-word queries as consecutive token sequences', () => {
    const m = findMatches(segs('the anual budgett was fine'), 'annual budget', true);
    expect(m).toHaveLength(1);
    const seg = 'the anual budgett was fine';
    expect(seg.slice(m[0].start, m[0].end)).toBe('anual budgett');
  });

  it('unencodable tokens (numbers) compare exactly', () => {
    expect(findMatches(segs('room 2024 booked'), '2024', true)).toHaveLength(1);
    expect(findMatches(segs('room 2025 booked'), '2024', true)).toEqual([]);
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd ui && npx vitest run src/lib/fuzzyMatch.test.ts`
Expected: FAIL — module not found

- [ ] **Step 4: Implement**

Create `ui/src/lib/fuzzyMatch.ts`:

```ts
import { doubleMetaphone } from 'double-metaphone';

/** One search hit inside a transcript: char offsets into that segment's text. */
export interface FindMatch {
  segmentIndex: number;
  start: number;
  end: number;
}

interface Token { text: string; start: number; end: number; code: string }

// Letters and digits, unicode-aware — mirrors the backend's WORD_RE.
const WORD_RE = /[\p{L}\p{N}]+/gu;

function tokenize(text: string): Token[] {
  const out: Token[] = [];
  for (const m of text.matchAll(WORD_RE)) {
    const raw = m[0];
    const lower = raw.toLowerCase();
    out.push({
      text: lower,
      start: m.index,
      end: m.index + raw.length,
      // Unencodable tokens (numbers, symbols) fall back to exact comparison.
      code: doubleMetaphone(raw)[0] || lower,
    });
  }
  return out;
}

/** True when a and b are within one insertion/deletion/substitution. */
function withinOneEdit(a: string, b: string): boolean {
  if (a === b) return true;
  const la = a.length, lb = b.length;
  if (Math.abs(la - lb) > 1) return false;
  if (la === lb) {
    let diff = 0;
    for (let i = 0; i < la; i++) if (a[i] !== b[i] && ++diff > 1) return false;
    return true;
  }
  const [s, l] = la < lb ? [a, b] : [b, a];
  let i = 0, j = 0, skipped = false;
  while (i < s.length && j < l.length) {
    if (s[i] === l[j]) { i++; j++; }
    else if (skipped) return false;
    else { skipped = true; j++; }
  }
  return true;
}

function tokensMatch(q: Token, t: Token): boolean {
  if (q.text === t.text) return true;
  if (q.code === t.code) return true;
  // Typo tolerance only for words long enough that one edit is unambiguous.
  return q.text.length >= 5 && t.text.length >= 5 && withinOneEdit(q.text, t.text);
}

/**
 * Find all matches of `query` across transcript segments.
 *
 * Exact mode: case-insensitive substring, one FindMatch per occurrence.
 * Fuzzy mode: the query's word tokens must match a consecutive run of the
 * segment's word tokens, each pair matching by Double Metaphone code
 * equality or edit distance ≤ 1 (both tokens ≥ 5 chars).
 */
export function findMatches(
  segments: { text: string }[],
  query: string,
  fuzzy: boolean,
): FindMatch[] {
  const q = query.trim();
  if (!q) return [];
  const out: FindMatch[] = [];

  if (!fuzzy) {
    const ql = q.toLowerCase();
    segments.forEach((seg, si) => {
      const lower = seg.text.toLowerCase();
      for (let hit = lower.indexOf(ql); hit !== -1; hit = lower.indexOf(ql, hit + ql.length)) {
        out.push({ segmentIndex: si, start: hit, end: hit + ql.length });
      }
    });
    return out;
  }

  const qTokens = tokenize(q);
  if (!qTokens.length) return [];
  segments.forEach((seg, si) => {
    const tokens = tokenize(seg.text);
    for (let p = 0; p + qTokens.length <= tokens.length; p++) {
      let ok = true;
      for (let j = 0; j < qTokens.length; j++) {
        if (!tokensMatch(qTokens[j], tokens[p + j])) { ok = false; break; }
      }
      if (ok) {
        out.push({
          segmentIndex: si,
          start: tokens[p].start,
          end: tokens[p + qTokens.length - 1].end,
        });
        p += qTokens.length - 1; // no overlapping matches
      }
    }
  });
  return out;
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ui && npx vitest run src/lib/fuzzyMatch.test.ts`
Expected: 8 PASS. If the `'cot'`/`'cat'` phonetic assumption is off (both encode to KT and DO match), that first assertion in `does not typo-match short words` is written tolerantly (`toBeLessThanOrEqual`) — only the `'car'` line must hold ('car' → KR ≠ 'cat' → KT).

- [ ] **Step 6: Commit**

```bash
git add ui/package.json ui/package-lock.json ui/src/lib/fuzzyMatch.ts ui/src/lib/fuzzyMatch.test.ts
git commit -m "feat(ui): fuzzy match util — metaphone + one-edit tokens, char-range hits"
```

---

### Task 7: `pendingFind` store

**Files:**
- Create: `ui/src/stores/pendingFind.ts`
- Test: `ui/src/stores/pendingFind.test.ts`

- [ ] **Step 1: Write the failing test**

Create `ui/src/stores/pendingFind.test.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest';
import { usePendingFind } from './pendingFind';

describe('usePendingFind', () => {
  beforeEach(() => usePendingFind.setState({ pending: null }));

  it('consume returns and clears a matching pending find', () => {
    usePendingFind.getState().set({ tid: 't1', query: 'budget', fuzzy: true, segmentIndex: 4 });
    const p = usePendingFind.getState().consume('t1');
    expect(p).toEqual({ tid: 't1', query: 'budget', fuzzy: true, segmentIndex: 4 });
    expect(usePendingFind.getState().consume('t1')).toBeNull();
  });

  it('consume for a different tid returns null and keeps the pending find', () => {
    usePendingFind.getState().set({ tid: 't1', query: 'q', fuzzy: false, segmentIndex: 0 });
    expect(usePendingFind.getState().consume('t2')).toBeNull();
    expect(usePendingFind.getState().pending?.tid).toBe('t1');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx vitest run src/stores/pendingFind.test.ts`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

Create `ui/src/stores/pendingFind.ts`:

```ts
import { create } from 'zustand';

/**
 * One-shot handoff from a library search hit to the transcript view:
 * "open transcript `tid` with the find bar pre-filled and jump to
 * `segmentIndex`". Consumed (cleared) by CompleteScreen on mount.
 */
export interface PendingFind {
  tid: string;
  query: string;
  fuzzy: boolean;
  segmentIndex: number;
}

interface State {
  pending: PendingFind | null;
  set: (p: PendingFind) => void;
  /** Return and clear the pending find if it targets `tid`; else null. */
  consume: (tid: string) => PendingFind | null;
}

export const usePendingFind = create<State>((set, get) => ({
  pending: null,
  set: (p) => set({ pending: p }),
  consume: (tid) => {
    const p = get().pending;
    if (!p || p.tid !== tid) return null;
    set({ pending: null });
    return p;
  },
}));
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npx vitest run src/stores/pendingFind.test.ts`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add ui/src/stores/pendingFind.ts ui/src/stores/pendingFind.test.ts
git commit -m "feat(ui): pendingFind store for library-hit → transcript jump"
```

---

### Task 8: CompleteScreen — fuzzy toggle, per-occurrence stepping, pending jump

**Files:**
- Modify: `ui/src/screens/CompleteScreen.tsx` (find logic :91-115, find bar :272-288, `highlight` :28-41, transcript render :320-321), `ui/src/styles/global.css` (find styles ~:738, mark styles ~:820)
- Test: append to `ui/src/screens/CompleteScreen.test.tsx`

- [ ] **Step 1: Write the failing tests**

Append to `ui/src/screens/CompleteScreen.test.tsx`, reusing that file's existing render helper / doc fixture and mock setup (it already mocks `@/platform`; follow its local conventions for props). New tests:

```tsx
import { usePendingFind } from '../stores/pendingFind';

// If the file has a local makeDoc/renderScreen helper, reuse it. Otherwise:
const findDoc = {
  version: 1,
  audio_path: '/x/a.mp3',
  duration_seconds: 10,
  language: 'en',
  speakers: { SPEAKER_00: 'Alice' },
  segments: [
    { start: 0, end: 2, speaker: 'SPEAKER_00', text: 'the cat sat on the cat mat' },
    { start: 2, end: 4, speaker: 'SPEAKER_00', text: 'nothing here' },
    { start: 4, end: 6, speaker: 'SPEAKER_00', text: 'Kaitlyn presented the plan' },
  ],
  models: {},
  created_at: '2026-07-15T10:00:00Z',
} as TranscriptDoc;

describe('in-transcript find', () => {
  it('counts occurrences, not segments', async () => {
    render(<CompleteScreen doc={findDoc} onRelabel={() => {}} />);
    const input = screen.getByLabelText('Search in transcript');
    fireEvent.change(input, { target: { value: 'cat' } });
    expect(await screen.findByText('1 / 2')).toBeInTheDocument();
  });

  it('fuzzy toggle finds phonetic matches', async () => {
    render(<CompleteScreen doc={findDoc} onRelabel={() => {}} />);
    fireEvent.change(screen.getByLabelText('Search in transcript'),
      { target: { value: 'Catelin' } });
    expect(await screen.findByText('0 / 0')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Fuzzy matching'));
    expect(await screen.findByText('1 / 1')).toBeInTheDocument();
    expect(screen.getByText('Kaitlyn').tagName).toBe('MARK');
  });

  it('consumes pendingFind: pre-fills query and jumps to the segment', async () => {
    usePendingFind.getState().set({ tid: 'T1', query: 'Kaitlyn', fuzzy: false, segmentIndex: 2 });
    render(<CompleteScreen doc={findDoc} tid="T1" onRelabel={() => {}} />);
    const input = screen.getByLabelText('Search in transcript') as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe('Kaitlyn'));
    expect(await screen.findByText('1 / 1')).toBeInTheDocument();
    expect(usePendingFind.getState().pending).toBeNull();
  });
});
```

Note: rendering with `tid` mounts AudioPanel — if the existing test file's platform mock doesn't cover AudioPanel's needs, mock it: `vi.mock('./AudioPanel', () => ({ AudioPanel: () => null }));` (check whether the file already does this). `scrollIntoView` is not implemented in jsdom — if the suite doesn't already stub it, add `Element.prototype.scrollIntoView = () => {};` in a `beforeAll`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ui && npx vitest run src/screens/CompleteScreen.test.tsx`
Expected: new tests FAIL (`1 / 2` not found — current code counts segments; no `Fuzzy matching` button); pre-existing tests still PASS

- [ ] **Step 3: Implement CompleteScreen changes**

In `ui/src/screens/CompleteScreen.tsx`:

**(a)** Add imports:

```tsx
import { findMatches, type FindMatch } from '../lib/fuzzyMatch';
import { usePendingFind } from '../stores/pendingFind';
```

**(b)** Replace the module-level `highlight` function (:28-41) with:

```tsx
function renderWithMarks(
  text: string,
  segIndex: number,
  matches: FindMatch[],
  currentIdx: number,
): ReactNode {
  const parts: ReactNode[] = [];
  let pos = 0;
  let any = false;
  matches.forEach((m, i) => {
    if (m.segmentIndex !== segIndex) return;
    any = true;
    if (m.start > pos) parts.push(text.slice(pos, m.start));
    parts.push(
      <mark key={i} className={i === currentIdx ? 'current' : undefined}>
        {text.slice(m.start, m.end)}
      </mark>,
    );
    pos = m.end;
  });
  if (!any) return text;
  parts.push(text.slice(pos));
  return parts;
}
```

**(c)** Replace the find state + matches logic (:49-50 and :91-115). Keep `findQ`/`findIdx`; add `findFuzzy` and `pendingSeg`:

```tsx
  const [findQ, setFindQ] = useState('');
  const [findIdx, setFindIdx] = useState(0);
  const [findFuzzy, setFindFuzzy] = useState(false);
  const [pendingSeg, setPendingSeg] = useState<number | null>(null);

  // One-shot handoff from a library search hit (see stores/pendingFind).
  useEffect(() => {
    if (!tid) return;
    const p = usePendingFind.getState().consume(tid);
    if (p) {
      setFindQ(p.query);
      setFindFuzzy(p.fuzzy);
      setPendingSeg(p.segmentIndex);
    }
  }, [tid]);

  const matches = useMemo(
    () => findMatches(doc.segments, findQ.trim(), findFuzzy),
    [doc.segments, findQ, findFuzzy],
  );

  useEffect(() => { setFindIdx(0); }, [findQ, findFuzzy]);

  // Applied after the reset above (declaration order): jump to the first
  // match at/after the clicked segment, or the last match as fallback.
  useEffect(() => {
    if (pendingSeg === null || !matches.length) return;
    let idx = matches.findIndex(m => m.segmentIndex >= pendingSeg);
    if (idx === -1) idx = matches.length - 1;
    setFindIdx(idx);
    setPendingSeg(null);
  }, [pendingSeg, matches]);

  const currentIdx = matches.length ? findIdx % matches.length : -1;
  const currentMatchSeg = currentIdx >= 0 ? matches[currentIdx].segmentIndex : null;
```

(The existing `seekRef`, `segRefs`, scroll effect on `currentMatchSeg`, and `step` stay exactly as they are.)

**(d)** In the find bar JSX (:272-288), add Escape handling and the fuzzy toggle. Replace the input's `onKeyDown` and add the toggle button before `{findQ.trim() && (`:

```tsx
        <input
          aria-label="Search in transcript"
          placeholder="Find in transcript…"
          value={findQ}
          onChange={e => setFindQ(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') step(e.shiftKey ? -1 : 1);
            else if (e.key === 'Escape') setFindQ('');
          }}
        />
        <button
          className={'find-fuzzy' + (findFuzzy ? ' on' : '')}
          aria-label="Fuzzy matching"
          aria-pressed={findFuzzy}
          title="Fuzzy matching — also finds words that sound alike"
          onClick={() => setFindFuzzy(f => !f)}
        >~ fuzzy</button>
```

**(e)** In the transcript render, replace the `highlight(...)` call (:321):

```tsx
                  {renderWithMarks(seg.text, i, matches, currentIdx)}
```

**(f)** In `ui/src/styles/global.css`, after the `.doc-find .icon-btn` rule (~:754), add:

```css
.find-fuzzy {
  font-family: var(--mono); font-size: 11px; white-space: nowrap;
  background: transparent; border: 0.5px solid var(--line); border-radius: 999px;
  color: var(--ink-dim); padding: 2px 8px; cursor: pointer;
}
.find-fuzzy.on {
  color: var(--accent); border-color: var(--accent-line);
  background: var(--accent-faint);
}
```

And after the `.transcript .turn p mark` rule (~:820), add:

```css
.transcript .turn p mark.current {
  background: var(--accent); color: var(--bg, #101012);
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ui && npx vitest run src/screens/CompleteScreen.test.tsx`
Expected: all PASS (new + pre-existing)

- [ ] **Step 5: Commit**

```bash
git add ui/src/screens/CompleteScreen.tsx ui/src/screens/CompleteScreen.test.tsx ui/src/styles/global.css
git commit -m "feat(ui): PDF-style find — per-occurrence stepping, fuzzy toggle, pending jump"
```

---

### Task 9: LibraryScreen — hit lines, toggles, click-to-jump

**Files:**
- Modify: `ui/src/screens/LibraryScreen.tsx`, `ui/src/styles/global.css` (after `.lib-snippet` rules ~:1066)
- Test: append to `ui/src/screens/LibraryScreen.test.tsx`

- [ ] **Step 1: Write the failing tests**

Append to `ui/src/screens/LibraryScreen.test.tsx` (reuse the file's existing mocks for `../api/client` / stores; seed state via `useLibrary.setState`). New tests:

```tsx
import { usePendingFind } from '../stores/pendingFind';

const hitItem = {
  id: 't1',
  path: '/lib/t1.json',
  audio_path: '/lib/meeting.mp3',
  duration_seconds: 60,
  speakers: 1,
  created_at: '2026-07-01T10:00:00Z',
  total_hits: 5,
  hits: [
    { segment_index: 2, start: 12, score: -2.0,
      snippet_parts: [{ text: 'about the ', match: false }, { text: 'budget', match: true }] },
    { segment_index: 7, start: 90, score: -1.5,
      snippet_parts: [{ text: 'budget', match: true }, { text: ' again', match: false }] },
    { segment_index: 9, start: 120, score: -1.2,
      snippet_parts: [{ text: 'more ', match: false }, { text: 'budget', match: true }] },
    { segment_index: 11, start: 150, score: -1.0,
      snippet_parts: [{ text: 'final ', match: false }, { text: 'budget', match: true }] },
  ],
};

describe('library segment hits', () => {
  it('renders up to 3 hit lines with a +N more expander', () => {
    useLibrary.setState({ items: [hitItem], all: [hitItem], query: 'budget' });
    render(<LibraryScreen setRoute={() => {}} setTid={() => {}} />);
    expect(screen.getAllByText('budget', { selector: 'mark' })).toHaveLength(3);
    const more = screen.getByRole('button', { name: '+2 more' }); // total_hits 5 − 3 shown
    fireEvent.click(more);
    expect(screen.getAllByText('budget', { selector: 'mark' })).toHaveLength(4);
  });

  it('clicking a hit sets pendingFind and opens the transcript', async () => {
    const setRoute = vi.fn();
    const setTid = vi.fn();
    useLibrary.setState({ items: [hitItem], all: [hitItem], query: 'budget', fuzzy: true });
    render(<LibraryScreen setRoute={setRoute} setTid={setTid} />);
    // The search input drives the store query in the real flow; type it so
    // the pendingFind query matches what the user searched.
    fireEvent.change(screen.getByPlaceholderText(/Search transcripts/), { target: { value: 'budget' } });
    fireEvent.click(screen.getAllByRole('button', { name: /Jump to match/ })[0]);
    await waitFor(() => expect(setTid).toHaveBeenCalledWith('t1'));
    expect(setRoute).toHaveBeenCalledWith('complete');
    expect(usePendingFind.getState().pending).toMatchObject({
      tid: 't1', query: 'budget', fuzzy: true, segmentIndex: 2,
    });
  });

  it('fuzzy toggle is wired to the store', () => {
    useLibrary.setState({ items: [], all: [], fuzzy: false });
    render(<LibraryScreen setRoute={() => {}} setTid={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'Fuzzy matching' }));
    expect(useLibrary.getState().fuzzy).toBe(true);
  });
});
```

Note: the hit-click test's `load(i.id)` call goes through `useTranscripts` — if the existing test file doesn't already mock it, add `useTranscripts.setState({ load: vi.fn(async () => {}) } as never)` or follow the file's established mocking pattern.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ui && npx vitest run src/screens/LibraryScreen.test.tsx`
Expected: new tests FAIL (no hit lines, no fuzzy button); pre-existing tests PASS

- [ ] **Step 3: Implement LibraryScreen changes**

In `ui/src/screens/LibraryScreen.tsx`:

**(a)** Add imports and helper:

```tsx
import { usePendingFind } from '../stores/pendingFind';
```

Below `fmtWhen`, add:

```tsx
function fmtTs(secs: number) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}
```

**(b)** In the component, add store selectors and expand state (after the existing selectors):

```tsx
  const fuzzy = useLibrary(s => s.fuzzy);
  const setFuzzy = useLibrary(s => s.setFuzzy);
  const sort = useLibrary(s => s.sort);
  const setSort = useLibrary(s => s.setSort);
  const [expanded, setExpanded] = useState<string | null>(null);
```

**(c)** In the `.lib-search` bar, after the clear button's closing `)}`, add the toggles:

```tsx
        <button
          className={'lib-toggle' + (fuzzy ? ' on' : '')}
          aria-label="Fuzzy matching"
          aria-pressed={fuzzy}
          title="Fuzzy matching — also finds words that sound alike"
          onClick={() => setFuzzy(!fuzzy)}
        >~ fuzzy</button>
        {isSearching && (
          <button
            className="lib-toggle"
            aria-label="Sort order"
            title="Toggle between relevance and date ordering"
            onClick={() => setSort(sort === 'relevance' ? 'date' : 'relevance')}
          >{sort === 'relevance' ? '↓ relevance' : '↓ date'}</button>
        )}
```

**(d)** Replace the snippet block (:132-140) with hits-aware rendering:

```tsx
                {i.hits && i.hits.length > 0 ? (
                  <div className="lib-hits">
                    {(expanded === i.id ? i.hits : i.hits.slice(0, 3)).map(h => (
                      <button
                        key={h.segment_index}
                        className="lib-hit"
                        aria-label={`Jump to match at segment ${h.segment_index}`}
                        onClick={async e => {
                          e.stopPropagation();
                          usePendingFind.getState().set({
                            tid: i.id,
                            query: q.trim(),
                            fuzzy,
                            segmentIndex: h.segment_index,
                          });
                          try { await load(i.id); setTid(i.id); setRoute('complete'); } catch {}
                        }}
                      >
                        {h.start != null && <span className="lib-hit-ts">{fmtTs(h.start)}</span>}
                        <span className="lib-hit-text">
                          {h.snippet_parts.map((p, idx) =>
                            p.match
                              ? <mark key={idx}>{p.text}</mark>
                              : <span key={idx}>{p.text}</span>
                          )}
                        </span>
                      </button>
                    ))}
                    {i.hits.length > 3 && expanded !== i.id && (
                      <button
                        className="lib-hit-more"
                        onClick={e => { e.stopPropagation(); setExpanded(i.id); }}
                      >+{(i.total_hits ?? i.hits.length) - 3} more</button>
                    )}
                  </div>
                ) : i.snippet_parts && i.snippet_parts.length > 0 && (
                  <div className="lib-snippet">
                    {i.snippet_parts.map((p, idx) =>
                      p.match
                        ? <mark key={idx}>{p.text}</mark>
                        : <span key={idx}>{p.text}</span>
                    )}
                  </div>
                )}
```

Also update the row's `has-snippet` class condition (:81) to include hits:

```tsx
                   className={'lib-row' + (i.error ? ' has-error' : '') + ((i.hits?.length || i.snippet_parts?.length) ? ' has-snippet' : '')}
```

**(e)** In `ui/src/styles/global.css`, after the `.lib-snippet mark` rule (~:1074), add:

```css
.lib-toggle {
  font-family: var(--mono); font-size: 11px; white-space: nowrap;
  background: transparent; border: 0.5px solid var(--line); border-radius: 999px;
  color: var(--ink-dim); padding: 2px 8px; cursor: pointer;
}
.lib-toggle.on {
  color: var(--accent); border-color: var(--accent-line);
  background: var(--accent-faint);
}

.lib-hits { display: flex; flex-direction: column; gap: 2px; padding: 2px 0 6px 30px; }
.lib-hit {
  display: flex; align-items: baseline; gap: 8px; text-align: left;
  background: transparent; border: none; border-radius: 4px;
  padding: 2px 6px; cursor: pointer; color: var(--ink-muted); font-size: 12px;
}
.lib-hit:hover { background: var(--accent-faint); }
.lib-hit-ts { font-family: var(--mono); font-size: 10px; color: var(--ink-dim); flex: none; }
.lib-hit-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lib-hit-text mark {
  background: var(--accent-faint); color: var(--accent);
  padding: 0 2px; border-radius: 2px;
}
.lib-hit-more {
  align-self: flex-start; background: transparent; border: none;
  color: var(--ink-dim); font-size: 11px; cursor: pointer; padding: 2px 6px;
}
.lib-hit-more:hover { color: var(--ink); }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ui && npx vitest run src/screens/LibraryScreen.test.tsx`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add ui/src/screens/LibraryScreen.tsx ui/src/screens/LibraryScreen.test.tsx ui/src/styles/global.css
git commit -m "feat(ui): library hit lines with jump-to-segment, fuzzy + sort toggles"
```

---

### Task 10: Full verification

**Files:** none new.

- [ ] **Step 1: Full Python suite**

Run: `.venv/bin/python -m pytest`
Expected: all PASS (baseline before this feature: 427 passed)

- [ ] **Step 2: Full UI suite + typecheck + build**

```bash
cd ui && npx vitest run && npx tsc --noEmit && npm run build && npm run build:hub
```

Expected: tests PASS, no type errors, both builds succeed.

- [ ] **Step 3: Fix anything that fails, commit fixes**

Any failure: fix, re-run the failing command, commit with a `fix:` message describing the actual cause.

- [ ] **Step 4: Update DEVLOG running log**

Append what surprised you (dead ends, gotchas) to `DEVLOG.md` under today's date. Do not commit DEVLOG.md (gitignored).

Device/runtime verification (Tauri app, hub web mode) is deferred to the user's batched manual session — note in the final summary what to manually test:
1. Library search → hit lines appear → click → transcript opens scrolled to line with query highlighted.
2. Fuzzy toggle on both screens ("Catelin" finds "Kaitlyn").
3. Relevance/date sort toggle.
4. Old `library.db` migrates (drops + reindexes) without errors on first launch.
