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


def test_phonetic_snippet_empty_text_returns_no_parts():
    assert _phonetic_snippet("", {"KTLN"}) == []


def test_phonetic_snippet_windows_long_text():
    filler = " ".join(f"word{i}" for i in range(40))
    text = f"{filler} Kaitlyn closes"
    parts = _phonetic_snippet(text, {encode_token("Kaitlyn")})
    joined = "".join(p["text"] for p in parts)
    assert joined.startswith("…")
    assert "word0 " not in joined
    assert [p["text"] for p in parts if p["match"]] == ["Kaitlyn"]
