"""SQLite-backed library index with FTS5 full-text search.

The transcript .json files on disk remain canonical and portable. This module
maintains a derived index for fast ranked search across:
- transcript text content (all segments joined)
- audio filename + full path
- speaker labels (after relabeling)
- language + ASR model metadata
- individual segments, indexed twice: verbatim (segments_fts) and with each
  word replaced by its Double Metaphone code (segments_phonetic) for fuzzy
  matching — both keyed by (transcript_id, segment_index, start)

The schema also reserves tables for future RAG work (chunks + embeddings),
so adding semantic search later does not require a migration of existing
rows — just population of the empty tables.

Sync model: the library directories registered with the app are the source
of truth. On startup (and after each transcribe completion) we walk those
directories, compare .json mtime/size with what we have indexed, and
upsert / delete to converge. The DB is throw-away: deleting library.db
forces a full re-index from disk and nothing is lost.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from speechtotext.api.phonetics import WORD_RE, encode_text, encode_token

_log = logging.getLogger(__name__)

SCHEMA_VERSION = 2

# Phonetic-only hits always rank below every exact hit; bm25 values are
# small negatives, so a large positive offset guarantees the ordering.
_PHONETIC_RANK_OFFSET = 1000.0
_HITS_PER_TRANSCRIPT = 5

# Private-use Unicode sentinels for FTS5 snippet() match markers. We split on
# these in Python and return plain-text parts so the frontend never receives
# HTML and can't accidentally render hostile transcript text as DOM.
_SNIPPET_START = ""
_SNIPPET_END = ""


def default_app_data_dir() -> Path:
    """Platform-appropriate writable app-data dir for LocalLexis."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "locallexis"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "locallexis"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "locallexis"


def default_db_path() -> Path:
    return default_app_data_dir() / "library.db"


_DDL = [
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER NOT NULL PRIMARY KEY
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transcripts (
        id              TEXT PRIMARY KEY,
        json_path       TEXT NOT NULL UNIQUE,
        audio_path      TEXT,
        audio_basename  TEXT,
        title           TEXT,
        duration_seconds REAL,
        language        TEXT,
        speakers_count  INTEGER,
        speaker_labels  TEXT,
        created_at      TEXT,
        json_mtime      REAL NOT NULL,
        json_size       INTEGER NOT NULL,
        models_asr      TEXT,
        models_diarizer TEXT,
        error           TEXT,
        origin          TEXT NOT NULL DEFAULT 'local',
        indexed_at      TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS transcripts_created ON transcripts(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS transcripts_json_path ON transcripts(json_path)",
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
        content,
        filename,
        speakers,
        meta,
        tokenize='porter unicode61 remove_diacritics 2'
    )
    """,
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
    # Forward-compat tables for RAG. Empty for now; populating them is a
    # separate feature. Defined here so adding semantic search later does
    # not require a schema migration of existing rows.
    """
    CREATE TABLE IF NOT EXISTS chunks (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
        idx           INTEGER NOT NULL,
        start_time    REAL,
        end_time      REAL,
        text          TEXT NOT NULL,
        token_count   INTEGER,
        version       INTEGER NOT NULL DEFAULT 1,
        UNIQUE(transcript_id, idx)
    )
    """,
    "CREATE INDEX IF NOT EXISTS chunks_transcript ON chunks(transcript_id)",
    """
    CREATE TABLE IF NOT EXISTS embeddings (
        chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
        model    TEXT NOT NULL,
        dim      INTEGER NOT NULL,
        vector   BLOB NOT NULL,
        version  INTEGER NOT NULL DEFAULT 1
    )
    """,
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("failed to read %s: %s", path, exc)
        return None


def _segment_text(doc: dict) -> str:
    parts: list[str] = []
    for seg in doc.get("segments") or []:
        t = seg.get("text")
        if t:
            parts.append(str(t))
    return " ".join(parts)


def _speaker_labels(doc: dict) -> str:
    speakers = doc.get("speakers") or {}
    if isinstance(speakers, dict):
        return " ".join(str(v) for v in speakers.values())
    return ""


def _meta_string(doc: dict, audio_basename: str) -> str:
    bits: list[str] = []
    if doc.get("language"):
        bits.append(str(doc["language"]))
    models = doc.get("models") or {}
    if isinstance(models, dict):
        for v in models.values():
            if v:
                bits.append(str(v))
    if doc.get("created_at"):
        bits.append(str(doc["created_at"])[:10])
    if audio_basename:
        bits.append(audio_basename)
    return " ".join(bits)


def _parse_snippet(raw: str) -> list[dict]:
    """Split an FTS5 snippet() result into [{text, match}] parts.

    The SQL uses private-use sentinels around matches; we split on them so
    the API returns structured text the client renders with React's normal
    escaping (via <mark>), never as raw HTML.
    """
    if not raw:
        return []
    parts: list[dict] = []
    chunks = raw.split(_SNIPPET_START)
    head = chunks[0]
    if head:
        parts.append({"text": head, "match": False})
    for chunk in chunks[1:]:
        if _SNIPPET_END in chunk:
            match_text, trailing = chunk.split(_SNIPPET_END, 1)
        else:
            match_text, trailing = chunk, ""
        if match_text:
            parts.append({"text": match_text, "match": True})
        if trailing:
            parts.append({"text": trailing, "match": False})
    return parts


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
        snippet = text[:200]
        return [{"text": snippet, "match": False}] if snippet else []
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


def _quote_fts(query: str) -> str:
    """Escape a free-text query for FTS5 MATCH.

    We do not expose FTS5's operator syntax to end users. Each whitespace-
    separated token is wrapped in double quotes (escaping internal quotes)
    and given a trailing '*' so prefix matches work without forcing the user
    to type one. Returns an empty string if nothing remains after stripping.
    """
    tokens: list[str] = []
    for raw in query.split():
        cleaned = raw.strip()
        if not cleaned:
            continue
        escaped = cleaned.replace('"', '""')
        tokens.append(f'"{escaped}"*')
    return " ".join(tokens)


class LibraryDB:
    """Thread-safe wrapper around a SQLite library index.

    The connection is opened with check_same_thread=False and protected by a
    re-entrant lock; the registry callers run in both the FastAPI request
    thread and the runner worker threads, so cross-thread access is normal.
    """

    def __init__(
        self, db_path: Path | None = None, *,
        hub_synced_dir: Path | None = None,
    ) -> None:
        self._hub_synced_dir = hub_synced_dir.resolve() if hub_synced_dir else None
        self.path = Path(db_path) if db_path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    # ── schema ─────────────────────────────────────────────────────────────

    def _migrate(self) -> None:
        known_paths: list[str] = []
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
                # version mismatch, drop everything and rebuild.
                #
                # BUT the rows are not fully derivable from the startup dirs:
                # runtime-registered dirs (audio parents via _on_complete_dir)
                # are persisted nowhere else, so the old rows are the only
                # memory of those files. Carry the known json_paths across
                # the rebuild and re-index every file that still exists —
                # otherwise transcripts outside the startup dirs silently
                # vanish from the library (v0.15.0 regression).
                try:
                    known_paths = [
                        r[0] for r in self._conn.execute(
                            "SELECT json_path FROM transcripts"
                        )
                    ]
                except sqlite3.OperationalError:
                    pass  # ancient/corrupt DB without a transcripts table
                #
                # NOTE: sqlite3 auto-commits before DDL statements, so this
                # `with self._conn` block is NOT atomic across the drops and
                # creates below. Crash-safety relies on every statement being
                # idempotent (DROP ... IF EXISTS / CREATE ... IF NOT EXISTS)
                # with the version row written last, so a re-run converges.
                # Future non-idempotent migrations must not reuse this
                # pattern blindly.
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
        # Additive, idempotent column add — intentionally NOT gated on
        # SCHEMA_VERSION. New DBs already have `origin` from _DDL; old DBs
        # get it here and existing rows take the column default ('local').
        # A version bump + branch would be over-engineering for a single
        # nullable-with-default column; the next non-additive migration
        # should still use the SCHEMA_VERSION mechanism above.
        with self._lock, self._conn:
            try:
                self._conn.execute(
                    "ALTER TABLE transcripts "
                    "ADD COLUMN origin TEXT NOT NULL DEFAULT 'local'"
                )
            except sqlite3.OperationalError:
                pass  # column already exists (new DB created from _DDL)
        with self._lock, self._conn:
            try:
                self._conn.execute("ALTER TABLE transcripts ADD COLUMN title TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists
        # After a drop-and-rebuild, restore the index for every file the old
        # schema knew about (upsert_path takes its own lock per file; files
        # deleted since are simply skipped and thus dropped from the index).
        for p in known_paths:
            path = Path(p)
            if path.exists():
                self.upsert_path(path)

    # ── indexing ──────────────────────────────────────────────────────────

    def upsert_path(self, json_path: Path) -> bool:
        """Index (or re-index) one .json file. Returns True if changed."""
        try:
            stat = json_path.stat()
        except OSError:
            return False
        doc = _read_json(json_path)
        if doc is None:
            # parse failure — record a stub so we don't reread on every sync
            return self._upsert_error(json_path, stat.st_mtime, stat.st_size, "parse")

        tid = json_path.stem
        audio_path = doc.get("audio_path")
        audio_basename = Path(audio_path).name if audio_path else json_path.name
        title = doc.get("title")
        title = str(title) if title is not None else None
        speakers = doc.get("speakers") or {}
        speaker_count = len(speakers) if isinstance(speakers, dict) else 0
        speaker_labels = _speaker_labels(doc)
        content = _segment_text(doc)
        models = doc.get("models") or {}
        meta = _meta_string(doc, audio_basename)
        fts_filename = f"{audio_basename} {title}" if title else audio_basename

        origin = "local"
        if self._hub_synced_dir is not None:
            try:
                json_path.resolve().relative_to(self._hub_synced_dir)
                origin = "hub"
            except ValueError:
                pass

        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO transcripts (
                    id, json_path, audio_path, audio_basename, title,
                    duration_seconds, language, speakers_count, speaker_labels,
                    created_at, json_mtime, json_size,
                    models_asr, models_diarizer, error, origin, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    json_path=excluded.json_path,
                    audio_path=excluded.audio_path,
                    audio_basename=excluded.audio_basename,
                    title=excluded.title,
                    duration_seconds=excluded.duration_seconds,
                    language=excluded.language,
                    speakers_count=excluded.speakers_count,
                    speaker_labels=excluded.speaker_labels,
                    created_at=excluded.created_at,
                    json_mtime=excluded.json_mtime,
                    json_size=excluded.json_size,
                    models_asr=excluded.models_asr,
                    models_diarizer=excluded.models_diarizer,
                    error=NULL,
                    origin=excluded.origin,
                    indexed_at=excluded.indexed_at
                """,
                (
                    tid,
                    str(json_path),
                    audio_path,
                    audio_basename,
                    title,
                    doc.get("duration_seconds"),
                    doc.get("language"),
                    speaker_count,
                    speaker_labels,
                    doc.get("created_at"),
                    stat.st_mtime,
                    stat.st_size,
                    str(models.get("asr") or "") or None,
                    str(models.get("diarizer") or "") or None,
                    origin,
                    _now_iso(),
                ),
            )
            rowid = self._conn.execute(
                "SELECT rowid FROM transcripts WHERE id=?", (tid,)
            ).fetchone()[0]
            # FTS5 doesn't support UPSERT; delete + insert for the row.
            self._conn.execute(
                "DELETE FROM transcripts_fts WHERE rowid=?", (rowid,)
            )
            self._conn.execute(
                "INSERT INTO transcripts_fts (rowid, content, filename, speakers, meta) "
                "VALUES (?, ?, ?, ?, ?)",
                (rowid, content, fts_filename, speaker_labels, meta),
            )
            # transcript_id is UNINDEXED, so each DELETE below is a full
            # scan of the FTS5 virtual table. Accepted deliberately: personal
            # libraries hold hundreds of transcripts, and the worst case is a
            # one-time full reindex after a schema bump.
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
        return True

    def _upsert_error(self, json_path: Path, mtime: float, size: int, err: str) -> bool:
        tid = json_path.stem
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO transcripts (
                    id, json_path, json_mtime, json_size, error, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    json_path=excluded.json_path,
                    json_mtime=excluded.json_mtime,
                    json_size=excluded.json_size,
                    error=excluded.error,
                    indexed_at=excluded.indexed_at
                """,
                (tid, str(json_path), mtime, size, err, _now_iso()),
            )
            rowid = self._conn.execute(
                "SELECT rowid FROM transcripts WHERE id=?", (tid,)
            ).fetchone()[0]
            self._conn.execute(
                "DELETE FROM transcripts_fts WHERE rowid=?", (rowid,)
            )
            self._conn.execute(
                "DELETE FROM segments_fts WHERE transcript_id=?", (tid,)
            )
            self._conn.execute(
                "DELETE FROM segments_phonetic WHERE transcript_id=?", (tid,)
            )
        return True

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

    def sync_dirs(self, dirs: Iterable[Path]) -> dict:
        """Reconcile the DB with the actual .json files in `dirs`.

        Returns counts: {scanned, upserted, deleted}. Cheap on subsequent
        runs because rows whose (mtime, size) match the on-disk file are
        skipped without re-reading content.
        """
        scanned = 0
        upserted = 0
        deleted = 0
        on_disk: set[str] = set()
        for d in dirs:
            if not d.is_dir():
                continue
            for json_path in d.glob("*.json"):
                scanned += 1
                p_str = str(json_path)
                on_disk.add(p_str)
                try:
                    stat = json_path.stat()
                except OSError:
                    continue
                with self._lock:
                    row = self._conn.execute(
                        "SELECT json_mtime, json_size FROM transcripts WHERE json_path=?",
                        (p_str,),
                    ).fetchone()
                if row and row["json_mtime"] == stat.st_mtime and row["json_size"] == stat.st_size:
                    continue
                if self.upsert_path(json_path):
                    upserted += 1
        # Drop rows that no longer have a file on disk *within the scanned dirs*.
        # We must not drop rows that belong to dirs the caller did not include
        # this round, so we restrict by parent prefix.
        if dirs:
            placeholders = ",".join("?" for _ in on_disk) if on_disk else "''"
            with self._lock:
                params: list = []
                like_clauses: list[str] = []
                for d in dirs:
                    like_clauses.append("json_path LIKE ?")
                    params.append(f"{d}{os.sep}%")
                clause = " OR ".join(like_clauses) if like_clauses else "0"
                if on_disk:
                    sql = (
                        f"SELECT json_path FROM transcripts WHERE ({clause}) "
                        f"AND json_path NOT IN ({placeholders})"
                    )
                    rows = self._conn.execute(sql, [*params, *on_disk]).fetchall()
                else:
                    sql = f"SELECT json_path FROM transcripts WHERE ({clause})"
                    rows = self._conn.execute(sql, params).fetchall()
            for r in rows:
                self.delete_by_path(Path(r["json_path"]))
                deleted += 1
        return {"scanned": scanned, "upserted": upserted, "deleted": deleted}

    # ── queries ───────────────────────────────────────────────────────────

    def list(self, limit: int = 200, offset: int = 0) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, json_path, audio_path, title, duration_seconds, language,
                       speakers_count, created_at, models_asr, models_diarizer,
                       error, origin
                FROM transcripts
                ORDER BY created_at DESC NULLS LAST, indexed_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

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
            # The two bm25 scales differ by orders of magnitude (per-segment
            # vs weighted transcript-level), so any transcript with a
            # body-segment hit intentionally outranks metadata-only
            # (title/speaker/filename) matches; the min() is a deliberate
            # "body match wins" rule, not a calibrated blend.
            rank_by_id[tid] = min(rank_by_id.get(tid, best), best)

        items = list(items_by_id.values())
        # Accepted limitation: date sort reorders the relevance-selected
        # candidate pool (top-`limit` transcript matches ∪ transcripts from
        # the top `limit*20` segment hits), so when total matches exceed
        # `limit` a newer low-relevance match can be omitted. Accepted
        # deliberately at personal-library scale (route default limit=200).
        if sort == "date":
            items.sort(key=lambda i: i.get("created_at") or "", reverse=True)
        else:
            items.sort(key=lambda i: rank_by_id.get(i["id"], 0.0))
        return items[:limit]

    def get_path(self, transcript_id: str) -> Path | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT json_path FROM transcripts WHERE id=?", (transcript_id,)
            ).fetchone()
        return Path(row["json_path"]) if row else None

    def list_since(self, since: float, limit: int = 10000, offset: int = 0) -> list[dict]:
        """Return transcripts whose json file mtime is greater than ``since``.

        Used by the sync delta endpoint to enumerate transcripts that
        have changed since the device's last sync cursor. Returns rows
        ordered by mtime ascending so callers can use the last row's
        mtime as the next cursor.

        The returned dicts carry ``json_path`` and ``json_mtime`` in
        addition to the usual library-listing fields, so callers can
        load the full transcript JSON from disk.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, json_path, audio_path, title, duration_seconds, language,
                       speakers_count, created_at, models_asr, models_diarizer,
                       error, origin, json_mtime
                FROM transcripts
                WHERE json_mtime > ?
                ORDER BY json_mtime ASC, json_path ASC
                LIMIT ? OFFSET ?
                """,
                (since, limit, offset),
            ).fetchall()
        items = []
        for r in rows:
            item = self._row_to_item(r)
            # _row_to_item exposes the JSON path as `path`. Surface it
            # under both names so sync delta callers (which load the
            # full doc from disk) don't have to know the indirection.
            item["json_path"] = r["json_path"]
            item["json_mtime"] = r["json_mtime"]
            items.append(item)
        return items

    def max_mtime(self) -> float:
        """Return the largest json_mtime in the index, or 0 if empty.

        Useful as the initial cursor returned by ``/sync/snapshot``.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(json_mtime) AS m FROM transcripts"
            ).fetchone()
        return float(row["m"]) if row and row["m"] is not None else 0.0

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row_to_item(r: sqlite3.Row) -> dict:
        models: dict[str, str] = {}
        if r["models_asr"]:
            models["asr"] = r["models_asr"]
        if r["models_diarizer"]:
            models["diarizer"] = r["models_diarizer"]
        item: dict = {
            "id": r["id"],
            "path": r["json_path"],
            "audio_path": r["audio_path"],
            "title": r["title"] if "title" in r.keys() else None,
            "duration_seconds": r["duration_seconds"],
            "language": r["language"],
            "speakers": r["speakers_count"] or 0,
            "created_at": r["created_at"],
            "models": models,
            "origin": (r["origin"] if "origin" in r.keys() else "local"),
        }
        if r["error"]:
            item["error"] = r["error"]
        return item
