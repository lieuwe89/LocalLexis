from __future__ import annotations

from speechtotext.summarize.prompt import build_summary_messages


def _doc():
    return {
        "title": "Standup",
        "language": "en",
        "speakers": {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"},
        "segments": [
            {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": "Morning."},
            {"start": 1.0, "end": 2.0, "speaker": "SPEAKER_01", "text": "Hi Alice."},
        ],
        "duration_seconds": 120.0,
    }


def test_messages_carry_speaker_labelled_lines():
    messages = build_summary_messages(_doc())
    assert messages[0]["role"] == "system"
    user = messages[1]["content"]
    assert "Alice: Morning." in user
    assert "Bob: Hi Alice." in user
    assert "Standup" in user


def test_unlabelled_speaker_falls_back_to_id():
    doc = _doc()
    del doc["speakers"]["SPEAKER_01"]
    user = build_summary_messages(doc)[1]["content"]
    assert "SPEAKER_01: Hi Alice." in user


def test_check_within_budget_ok():
    from speechtotext.summarize.prompt import check_within_budget
    check_within_budget([{"role": "user", "content": "short"}])  # no raise


def test_check_within_budget_rejects_oversized():
    from speechtotext.summarize.prompt import check_within_budget, TranscriptTooLongError
    import pytest
    huge = [{"role": "user", "content": "x" * 600_000}]  # ~150k tokens
    with pytest.raises(TranscriptTooLongError, match="too long"):
        check_within_budget(huge)


def test_system_prompt_flags_spoken_asr_nature():
    """The summarizer must know it's reading imperfect ASR output of speech,
    so it compensates for mis-transcriptions instead of quoting them."""
    sysmsg = build_summary_messages(_doc())[0]["content"].lower()
    assert "speech recognition" in sysmsg
    assert "spoken" in sysmsg
    # tells the model to infer intended meaning through transcription errors
    assert "mis" in sysmsg  # misheard / mis-transcription
