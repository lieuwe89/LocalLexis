from __future__ import annotations

from speechtotext.rag.chunker import MAX_WORDS, TARGET_WORDS, build_chunks


def _doc(segments):
    return {"segments": [
        {"start": s, "end": e, "speaker": "SPEAKER_00", "text": t}
        for s, e, t in segments
    ]}


def test_merges_short_segments_until_target():
    # 3 segments of 60 words each; 60+60=120 < 150, +60=180 ≥ 150 → one chunk of 180 words.
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
