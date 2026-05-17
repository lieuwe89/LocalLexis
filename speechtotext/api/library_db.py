"""SQLite-backed library index with FTS5 full-text search.

The transcript .json files on disk remain canonical and portable. This module
maintains a derived index for fast ranked search across:
- transcript text content (all segments joined)
- audio filename + full path
- speaker labels (after relabeling)
- language + ASR model metadata

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

_log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def default_app_data_dir() -> Path:
    """Platform-appropriate writable app-data dir for LocalScribe."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "localscribe"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "localscribe"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "localscribe"


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

    def __init__(self, db_path: Path | None = None) -> None:
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
        with self._lock, self._conn:
            for stmt in _DDL:
                self._conn.execute(stmt)
            row = self._conn.execute(
                "SELECT version FROM schema_version LIMIT 1"
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (SCHEMA_VERSION,),
                )
            # Future migrations: bump SCHEMA_VERSION and branch on row[0].

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
        speakers = doc.get("speakers") or {}
        speaker_count = len(speakers) if isinstance(speakers, dict) else 0
        speaker_labels = _speaker_labels(doc)
        content = _segment_text(doc)
        models = doc.get("models") or {}
        meta = _meta_string(doc, audio_basename)

        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO transcripts (
                    id, json_path, audio_path, audio_basename,
                    duration_seconds, language, speakers_count, speaker_labels,
                    created_at, json_mtime, json_size,
                    models_asr, models_diarizer, error, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(id) DO UPDATE SET
                    json_path=excluded.json_path,
                    audio_path=excluded.audio_path,
                    audio_basename=excluded.audio_basename,
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
                    indexed_at=excluded.indexed_at
                """,
                (
                    tid,
                    str(json_path),
                    audio_path,
                    audio_basename,
                    doc.get("duration_seconds"),
                    doc.get("language"),
                    speaker_count,
                    speaker_labels,
                    doc.get("created_at"),
                    stat.st_mtime,
                    stat.st_size,
                    str(models.get("asr") or "") or None,
                    str(models.get("diarizer") or "") or None,
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
                (rowid, content, audio_basename, speaker_labels, meta),
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
        return True

    def delete_by_path(self, json_path: Path) -> None:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT rowid FROM transcripts WHERE json_path=?",
                (str(json_path),),
            ).fetchone()
            if row is None:
                return
            self._conn.execute(
                "DELETE FROM transcripts_fts WHERE rowid=?", (row["rowid"],)
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
                SELECT id, json_path, audio_path, duration_seconds, language,
                       speakers_count, created_at, models_asr, models_diarizer, error
                FROM transcripts
                ORDER BY created_at DESC NULLS LAST, indexed_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def search(self, query: str, limit: int = 50) -> list[dict]:
        match = _quote_fts(query)
        if not match:
            return self.list(limit=limit)
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT t.id, t.json_path, t.audio_path, t.duration_seconds,
                       t.language, t.speakers_count, t.created_at,
                       t.models_asr, t.models_diarizer, t.error,
                       snippet(transcripts_fts, 0, '<mark>', '</mark>', '…', 24) AS snippet,
                       bm25(transcripts_fts, 4.0, 6.0, 3.0, 2.0) AS rank
                FROM transcripts_fts
                JOIN transcripts t ON t.rowid = transcripts_fts.rowid
                WHERE transcripts_fts MATCH ?
                ORDER BY rank ASC
                LIMIT ?
                """,
                (match, limit),
            ).fetchall()
        items = []
        for r in rows:
            item = self._row_to_item(r)
            item["snippet"] = r["snippet"]
            items.append(item)
        return items

    def get_path(self, transcript_id: str) -> Path | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT json_path FROM transcripts WHERE id=?", (transcript_id,)
            ).fetchone()
        return Path(row["json_path"]) if row else None

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
            "duration_seconds": r["duration_seconds"],
            "language": r["language"],
            "speakers": r["speakers_count"] or 0,
            "created_at": r["created_at"],
            "models": models,
        }
        if r["error"]:
            item["error"] = r["error"]
        return item
