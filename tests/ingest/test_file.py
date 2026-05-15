import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from speechtotext.ingest.file import IngestError, normalize_to_wav


def test_runs_ffmpeg_with_correct_args(tmp_path: Path):
    src = tmp_path / "a.mp3"
    src.write_bytes(b"fake")
    out = tmp_path / "out.wav"

    with patch("speechtotext.ingest.file.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        normalize_to_wav(src, out)

    args = run.call_args.args[0]
    assert args[0] == "ffmpeg"
    assert "-ac" in args and "1" in args
    assert "-ar" in args and "16000" in args
    assert str(src) in args
    assert str(out) in args


def test_raises_on_ffmpeg_failure(tmp_path: Path):
    src = tmp_path / "a.mp3"
    src.write_bytes(b"fake")
    with patch("speechtotext.ingest.file.subprocess.run") as run:
        run.return_value.returncode = 1
        run.return_value.stderr = "bad codec"
        with pytest.raises(IngestError, match="bad codec"):
            normalize_to_wav(src, tmp_path / "out.wav")


def test_raises_when_ffmpeg_missing(tmp_path: Path):
    src = tmp_path / "a.mp3"
    src.write_bytes(b"fake")
    with patch(
        "speechtotext.ingest.file.subprocess.run", side_effect=FileNotFoundError
    ):
        with pytest.raises(IngestError, match="ffmpeg not found"):
            normalize_to_wav(src, tmp_path / "out.wav")


def test_input_missing(tmp_path: Path):
    with pytest.raises(IngestError, match="does not exist"):
        normalize_to_wav(tmp_path / "missing.mp3", tmp_path / "out.wav")
