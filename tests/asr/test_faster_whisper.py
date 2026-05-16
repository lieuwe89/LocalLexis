from pathlib import Path
from unittest.mock import MagicMock, patch

from speechtotext.asr.faster_whisper import FasterWhisperASR
from speechtotext.models import Segment


def _fake_whisper_segment(start: float, end: float, text: str):
    s = MagicMock()
    s.start = start
    s.end = end
    s.text = text
    return s


def test_transcribe_returns_segments(tmp_path: Path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"fake")

    fake_segments = iter(
        [
            _fake_whisper_segment(0.0, 1.0, "hello"),
            _fake_whisper_segment(1.0, 2.0, "world"),
        ]
    )
    fake_info = MagicMock(language="en")

    with patch("speechtotext.asr.faster_whisper.WhisperModel") as Model:
        instance = Model.return_value
        instance.transcribe.return_value = (fake_segments, fake_info)

        asr = FasterWhisperASR(model_size="tiny", backend="cpu")
        result = asr.transcribe(wav, language=None)

    assert len(result) == 2
    assert isinstance(result[0], Segment)
    assert result[0].text == "hello"
    assert result[0].language == "en"


def test_backend_to_device_mapping():
    with patch("speechtotext.asr.faster_whisper.WhisperModel") as Model:
        FasterWhisperASR(model_size="tiny", backend="cuda")
        kwargs = Model.call_args.kwargs
        assert kwargs["device"] == "cuda"
        assert kwargs["compute_type"] == "float16"

    with patch("speechtotext.asr.faster_whisper.WhisperModel") as Model:
        FasterWhisperASR(model_size="tiny", backend="mps")
        kwargs = Model.call_args.kwargs
        assert kwargs["device"] == "cpu"  # mps not yet supported by CTranslate2
        assert kwargs["compute_type"] == "int8"

    with patch("speechtotext.asr.faster_whisper.WhisperModel") as Model:
        FasterWhisperASR(model_size="tiny", backend="cpu")
        kwargs = Model.call_args.kwargs
        assert kwargs["device"] == "cpu"
        assert kwargs["compute_type"] == "int8"


def test_language_passed_through(tmp_path: Path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"fake")
    fake_info = MagicMock(language="nl")
    with patch("speechtotext.asr.faster_whisper.WhisperModel") as Model:
        instance = Model.return_value
        instance.transcribe.return_value = (iter([]), fake_info)
        asr = FasterWhisperASR(model_size="tiny", backend="cpu")
        asr.transcribe(wav, language="nl")
        assert instance.transcribe.call_args.kwargs["language"] == "nl"


def test_bundled_model_takes_precedence_over_name(tmp_path: Path, monkeypatch):
    bundled_root = tmp_path / "bundled"
    model_dir = bundled_root / "faster-whisper-base.en"
    model_dir.mkdir(parents=True)
    (model_dir / "model.bin").write_bytes(b"fake")
    monkeypatch.setenv("LOCALSCRIBE_BUNDLED_MODELS", str(bundled_root))

    with patch("speechtotext.asr.faster_whisper.WhisperModel") as Model:
        FasterWhisperASR(model_size="base.en", backend="cpu")
        kwargs = Model.call_args.kwargs
        assert kwargs["model_size_or_path"] == str(model_dir)
        assert kwargs["download_root"] is None


def test_falls_back_to_name_when_no_bundled_match(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALSCRIBE_BUNDLED_MODELS", str(tmp_path))
    with patch("speechtotext.asr.faster_whisper.WhisperModel") as Model:
        FasterWhisperASR(model_size="medium", backend="cpu", download_root=tmp_path / "cache")
        kwargs = Model.call_args.kwargs
        assert kwargs["model_size_or_path"] == "medium"
        assert kwargs["download_root"] == str(tmp_path / "cache")
