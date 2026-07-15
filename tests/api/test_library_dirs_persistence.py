"""Tests for persistence of runtime-registered library dirs.

Dirs registered at runtime (_on_complete_dir adds the audio parent on job
completion, _on_synced adds the hub synced dir) must survive restarts and
schema rebuilds — the DB rows alone are a hidden source of record that a
drop-and-rebuild migration can wipe (the v0.15.0 regression).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from speechtotext.api.library_db import SCHEMA_VERSION, LibraryDB


def _make_doc(text: str = "hello world") -> dict:
    return {
        "version": 1,
        "audio_path": "/some/dir/meeting.mp3",
        "duration_seconds": 1.0,
        "language": "en",
        "speakers": {"SPEAKER_00": "Alice"},
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": text}],
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


def test_register_dir_round_trips(db: LibraryDB, tmp_path: Path):
    d = tmp_path / "recordings"
    d.mkdir()
    db.register_dir(d)
    assert db.known_dirs() == [d.resolve()]


def test_register_dir_dedupes(db: LibraryDB, tmp_path: Path):
    d = tmp_path / "recordings"
    d.mkdir()
    db.register_dir(d)
    db.register_dir(d)
    db.register_dir(d.resolve())  # different spelling, same dir
    assert db.known_dirs() == [d.resolve()]
    rows = db._conn.execute("SELECT COUNT(*) FROM library_dirs").fetchone()
    assert rows[0] == 1


def test_known_dirs_survive_reopen(tmp_path: Path):
    db_path = tmp_path / "library.db"
    d = tmp_path / "recordings"
    d.mkdir()
    db = LibraryDB(db_path)
    db.register_dir(d)
    db.close()

    db2 = LibraryDB(db_path)
    assert db2.known_dirs() == [d.resolve()]
    db2.close()


def test_known_dirs_prunes_missing_dirs(db: LibraryDB, tmp_path: Path):
    kept = tmp_path / "kept"
    kept.mkdir()
    gone = tmp_path / "gone"
    gone.mkdir()
    db.register_dir(kept)
    db.register_dir(gone)
    gone.rmdir()
    assert db.known_dirs() == [kept.resolve()]
    # The pruned row is deleted, not just filtered out of the return value.
    rows = db._conn.execute("SELECT path FROM library_dirs").fetchall()
    assert [r["path"] for r in rows] == [str(kept.resolve())]


def test_known_dirs_no_prune_keeps_rows(db: LibraryDB, tmp_path: Path):
    gone = tmp_path / "gone"
    gone.mkdir()
    db.register_dir(gone)
    gone.rmdir()
    assert db.known_dirs(prune=False) == []
    rows = db._conn.execute("SELECT path FROM library_dirs").fetchall()
    assert len(rows) == 1


def test_registered_dirs_survive_schema_rebuild(tmp_path: Path):
    """library_dirs is persistent state, not a rebuildable index — the
    drop-and-rebuild migration must leave it intact."""
    db_path = tmp_path / "library.db"
    d = tmp_path / "outside-dir"
    d.mkdir()
    db = LibraryDB(db_path)
    db.register_dir(d)
    # Simulate an old-schema DB by forging a stale version number.
    db._conn.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION - 1,))
    db._conn.commit()
    db.close()

    db2 = LibraryDB(db_path)
    row = db2._conn.execute("SELECT version FROM schema_version").fetchone()
    assert row[0] == SCHEMA_VERSION
    assert db2.known_dirs() == [d.resolve()]
    db2.close()


def test_old_db_without_table_gets_it_added(tmp_path: Path):
    """DBs created before library_dirs existed gain the table on open."""
    import sqlite3

    db_path = tmp_path / "library.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE schema_version (version INTEGER NOT NULL PRIMARY KEY)"
    )
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    conn.commit()
    conn.close()

    db = LibraryDB(db_path)
    d = tmp_path / "recordings"
    d.mkdir()
    db.register_dir(d)
    assert db.known_dirs() == [d.resolve()]
    db.close()


# ── app wiring ────────────────────────────────────────────────────────────


def test_on_complete_dir_registration_survives_restart(tmp_path: Path):
    """A dir registered via the job-completion callback must reappear in
    app.state.library_dirs when a fresh app boots on the same DB."""
    from speechtotext.api.app import create_app

    db_path = tmp_path / "library.db"
    d = tmp_path / "recordings"
    d.mkdir()
    _write(d, "alpha", _make_doc())

    app1 = create_app(library_db_path=db_path, devices_db_path=tmp_path / "dev1.db")
    # The callback fires a background sync_dirs thread; stub it so closing
    # the DB right after doesn't race the daemon thread.
    app1.state.library_db.sync_dirs = lambda dirs: None
    app1.state.jobs._on_complete_dir(d)
    assert d in app1.state.library_dirs
    app1.state.library_db.close()

    app2 = create_app(library_db_path=db_path, devices_db_path=tmp_path / "dev2.db")
    assert d.resolve() in app2.state.library_dirs
    app2.state.library_db.close()


def test_on_synced_registration_survives_restart(tmp_path: Path, monkeypatch):
    """The hub synced dir registered via _on_synced must also persist."""
    import speechtotext.api.app as app_module
    from speechtotext.client import paths as client_paths

    synced = client_paths.synced_dir()
    synced.mkdir(parents=True, exist_ok=True)

    db_path = tmp_path / "library.db"
    app1 = app_module.create_app(
        library_db_path=db_path, devices_db_path=tmp_path / "dev1.db"
    )
    app1.state.hub_runtime._on_synced([])
    rows = app1.state.library_db._conn.execute(
        "SELECT path FROM library_dirs"
    ).fetchall()
    assert [r["path"] for r in rows] == [str(synced.resolve())]
    app1.state.library_db.close()


def test_restart_recovers_transcripts_after_db_loss(tmp_path: Path):
    """The end-to-end failure mode this feature exists for: registered dir
    known → DB index rows wiped by a rebuild → next boot rescans the dir
    and the transcripts come back."""
    from speechtotext.api.app import create_app

    db_path = tmp_path / "library.db"
    d = tmp_path / "recordings"
    d.mkdir()
    p = _write(d, "alpha", _make_doc("needle in haystack"))

    app1 = create_app(library_db_path=db_path, devices_db_path=tmp_path / "dev1.db")
    app1.state.library_db.sync_dirs = lambda dirs: None  # avoid daemon-thread race
    app1.state.jobs._on_complete_dir(d)
    app1.state.library_db.upsert_path(p)
    # Simulate a future migration bug that wipes the index rows but (per
    # design) leaves library_dirs intact.
    with app1.state.library_db._lock, app1.state.library_db._conn:
        app1.state.library_db._conn.execute("DELETE FROM transcripts")
    app1.state.library_db.close()

    app2 = create_app(library_db_path=db_path, devices_db_path=tmp_path / "dev2.db")
    assert d.resolve() in app2.state.library_dirs
    app2.state.library_db.sync_dirs(app2.state.library_dirs)
    assert "alpha" in [r["id"] for r in app2.state.library_db.list()]
    app2.state.library_db.close()
