import json
from pathlib import Path

from speechtotext.api.library_db import LibraryDB


def _write_doc(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "audio_path": "/x/a.wav",
        "segments": [{"speaker": "SPEAKER_00", "text": "hi"}],
    }), encoding="utf-8")


def test_local_doc_gets_origin_local(tmp_path):
    db = LibraryDB(tmp_path / "lib.db")
    doc = tmp_path / "out" / "a.json"
    _write_doc(doc)
    db.upsert_path(doc)
    items = db.list()
    assert items[0]["origin"] == "local"


def test_hub_synced_doc_gets_origin_hub(tmp_path):
    synced = tmp_path / "hub" / "synced"
    db = LibraryDB(tmp_path / "lib.db", hub_synced_dir=synced)
    doc = synced / "t1.json"
    _write_doc(doc)
    db.upsert_path(doc)
    assert db.list()[0]["origin"] == "hub"


def test_search_surfaces_origin(tmp_path):
    synced = tmp_path / "hub" / "synced"
    db = LibraryDB(tmp_path / "lib.db", hub_synced_dir=synced)
    hub_doc = synced / "t1.json"
    hub_doc.parent.mkdir(parents=True, exist_ok=True)
    hub_doc.write_text(json.dumps({
        "audio_path": "/x/meeting.wav",
        "segments": [{"speaker": "SPEAKER_00", "text": "quarterly numbers"}],
    }), encoding="utf-8")
    db.upsert_path(hub_doc)
    hits = db.search("quarterly")
    assert hits and hits[0]["origin"] == "hub"


def test_existing_db_migrates_origin_column(tmp_path):
    db_path = tmp_path / "lib.db"
    db = LibraryDB(db_path)
    doc = tmp_path / "a.json"
    _write_doc(doc)
    db.upsert_path(doc)
    db.close()
    # Reopen — the ALTER-TABLE migration path must not raise and rows
    # default to 'local'.
    db2 = LibraryDB(db_path)
    assert db2.list()[0]["origin"] == "local"
