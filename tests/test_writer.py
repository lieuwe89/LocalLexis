import json
from datetime import datetime, timezone
from pathlib import Path

from speechtotext.models import LabeledSegment, Transcript
from speechtotext.writer import format_txt, write_transcript


def _transcript(audio: Path) -> Transcript:
    return Transcript(
        audio_path=audio,
        duration_seconds=4.0,
        language="en",
        speakers={"SPEAKER_00": "Speaker 1", "SPEAKER_01": "Speaker 2"},
        segments=[
            LabeledSegment(0.0, 2.0, "hello", "SPEAKER_00"),
            LabeledSegment(2.0, 4.0, "hi there", "SPEAKER_01"),
        ],
        models={"asr": "faster-whisper:large-v3", "diarizer": "pyannote:4.0", "backend": "cpu"},
        created_at=datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc),
    )


def test_writes_sibling_files(tmp_path: Path):
    audio = tmp_path / "rec.mp3"
    audio.write_bytes(b"fake")
    tr = _transcript(audio)

    write_transcript(tr)

    txt = audio.with_suffix(".txt")
    js = audio.with_suffix(".json")
    assert txt.exists()
    assert js.exists()
    data = json.loads(js.read_text())
    assert data["version"] == 1
    assert data["language"] == "en"
    assert data["speakers"]["SPEAKER_00"] == "Speaker 1"
    assert len(data["segments"]) == 2
    assert data["segments"][0]["text"] == "hello"


def test_txt_format(tmp_path: Path):
    audio = tmp_path / "rec.mp3"
    audio.write_bytes(b"fake")
    txt = format_txt(_transcript(audio))
    assert "[00:00:00] Speaker 1: hello" in txt
    assert "[00:00:02] Speaker 2: hi there" in txt


def test_no_temp_files_left(tmp_path: Path):
    audio = tmp_path / "rec.mp3"
    audio.write_bytes(b"fake")
    write_transcript(_transcript(audio))
    assert not any(tmp_path.glob("*.tmp"))


def test_atomic_replace(tmp_path: Path):
    audio = tmp_path / "rec.mp3"
    audio.write_bytes(b"fake")
    (audio.with_suffix(".json")).write_text('{"old": true}')
    write_transcript(_transcript(audio))
    data = json.loads(audio.with_suffix(".json").read_text())
    assert "old" not in data
    assert data["version"] == 1
