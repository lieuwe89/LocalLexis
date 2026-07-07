from __future__ import annotations

import json
from pathlib import Path

from speechtotext.api.library_db import LibraryDB


def _doc(title=None):
    d = {
        "audio_path": "/tmp/a.wav",
        "duration_seconds": 1.0,
        "language": "en",
        "speakers": {},
        "segments": [{"start": 0, "end": 1, "speaker": "S", "text": "hi"}],
        "models": {},
        "created_at": "2026-07-07T10:00:00+00:00",
    }
    if title:
        d["title"] = title
    return d


def test_title_in_list_and_search(tmp_path: Path):
    p = tmp_path / "rec.json"
    p.write_text(json.dumps(_doc(title="Board meeting")), encoding="utf-8")
    db = LibraryDB(tmp_path / "library.db")
    db.upsert_path(p)
    items = db.list()
    assert items[0]["title"] == "Board meeting"
    hits = db.search("board")
    assert len(hits) == 1 and hits[0]["id"] == "rec"


def test_title_absent_is_none(tmp_path: Path):
    p = tmp_path / "rec.json"
    p.write_text(json.dumps(_doc()), encoding="utf-8")
    db = LibraryDB(tmp_path / "library.db")
    db.upsert_path(p)
    assert db.list()[0]["title"] is None


def test_title_migration_on_existing_db(tmp_path: Path):
    # open once (creates schema), close, reopen — the additive ALTER must
    # be idempotent, mirroring the `origin` column pattern
    db = LibraryDB(tmp_path / "library.db")
    db.close()
    db2 = LibraryDB(tmp_path / "library.db")
    db2.close()
