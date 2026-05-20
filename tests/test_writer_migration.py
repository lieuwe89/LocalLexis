"""Tests for the v1 -> v2 transcript schema migration.

The writer now emits v2 (with ``_workspace_id``, ``_clocks``, ``_history``).
Existing v1 transcripts on disk must still load through every reader
without modification — the relabel CLI and the library index both walk
old JSON files in users' libraries.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from speechtotext.models import LabeledSegment, Transcript
from speechtotext.relabel import relabel
from speechtotext.writer import _SCHEMA_VERSION


def _v1_doc(audio_path: Path) -> dict:
    """A transcript JSON in the pre-block-2 schema (no v2 fields)."""
    return {
        "version": 1,
        "audio_path": str(audio_path),
        "duration_seconds": 4.0,
        "language": "en",
        "speakers": {"SPEAKER_00": "Speaker 1", "SPEAKER_01": "Speaker 2"},
        "segments": [
            {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00", "text": "hello"},
            {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_01", "text": "hi"},
        ],
        "models": {"asr": "faster-whisper:tiny"},
        "created_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc).isoformat(),
    }


def test_schema_version_is_2() -> None:
    assert _SCHEMA_VERSION == 2


def test_relabel_preserves_unknown_fields(tmp_path: Path) -> None:
    """v2 fields written by the new writer must round-trip through the
    relabel CLI even though relabel does not touch them."""
    audio = tmp_path / "rec.mp3"
    audio.write_bytes(b"fake")
    json_path = audio.with_suffix(".json")
    doc = _v1_doc(audio)
    doc["_workspace_id"] = "ws_test"
    doc["_clocks"] = {
        "speakers.SPEAKER_00": {
            "device": "hub-test",
            "lamport": 3,
            "ts": "2026-05-20T00:00:00Z",
        }
    }
    doc["_history"] = [
        {
            "op": "relabel",
            "key": "speakers.SPEAKER_00",
            "value": "Speaker 1",
            "from_value": None,
            "device": "hub-test",
            "lamport": 3,
            "ts": "2026-05-20T00:00:00Z",
        }
    ]
    json_path.write_text(json.dumps(doc), encoding="utf-8")
    audio.with_suffix(".txt").write_text("placeholder")

    relabel(json_path, {"SPEAKER_00": "Alice"})

    after = json.loads(json_path.read_text(encoding="utf-8"))
    assert after["speakers"]["SPEAKER_00"] == "Alice"
    # Critically: v2 fields survive the relabel round-trip.
    assert after["_workspace_id"] == "ws_test"
    assert after["_clocks"]
    assert after["_history"]


def test_relabel_works_on_v1_transcripts(tmp_path: Path) -> None:
    """A library that pre-dates the block-2 changes must still relabel
    cleanly even though its JSONs lack v2 fields."""
    audio = tmp_path / "rec.mp3"
    audio.write_bytes(b"fake")
    json_path = audio.with_suffix(".json")
    json_path.write_text(json.dumps(_v1_doc(audio)), encoding="utf-8")
    audio.with_suffix(".txt").write_text("placeholder")

    relabel(json_path, {"SPEAKER_00": "Alice"})

    after = json.loads(json_path.read_text(encoding="utf-8"))
    assert after["speakers"]["SPEAKER_00"] == "Alice"
    # Old transcripts stay at version 1 — relabel only touches speakers.
    assert after["version"] == 1


def test_library_db_indexes_v2_transcripts(tmp_path: Path) -> None:
    from speechtotext.api.library_db import LibraryDB
    from speechtotext.writer import write_transcript

    audio = tmp_path / "rec.mp3"
    audio.write_bytes(b"fake")
    transcript = Transcript(
        audio_path=audio,
        duration_seconds=2.0,
        language="en",
        speakers={"SPEAKER_00": "Alice"},
        segments=[LabeledSegment(0.0, 2.0, "hello", "SPEAKER_00")],
        models={"asr": "faster-whisper:tiny"},
        created_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    write_transcript(transcript, workspace_id="ws_test")

    db = LibraryDB(db_path=tmp_path / "library.db")
    try:
        result = db.sync_dirs([tmp_path])
        assert result["upserted"] == 1
        rows = db.list()
        assert len(rows) == 1
        assert rows[0]["id"] == "rec"
    finally:
        db.close()


def test_library_db_indexes_v1_transcripts(tmp_path: Path) -> None:
    from speechtotext.api.library_db import LibraryDB

    audio = tmp_path / "old.mp3"
    audio.write_bytes(b"fake")
    json_path = audio.with_suffix(".json")
    json_path.write_text(json.dumps(_v1_doc(audio)), encoding="utf-8")

    db = LibraryDB(db_path=tmp_path / "library.db")
    try:
        result = db.sync_dirs([tmp_path])
        assert result["upserted"] == 1
        rows = db.list()
        assert len(rows) == 1
        assert rows[0]["id"] == "old"
    finally:
        db.close()
