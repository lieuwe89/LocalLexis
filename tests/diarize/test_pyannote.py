from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from speechtotext.diarize.pyannote import PyannoteDiarizer
from speechtotext.models import SpeakerTurn


def _patch_sf_read():
    """soundfile.read mock that returns silent stereo at 16 kHz."""
    return patch(
        "soundfile.read",
        return_value=(np.zeros((1600, 1), dtype=np.float32), 16000),
    )


def _fake_annotation(turns: list[tuple[float, float, str]]):
    """Build a fake pyannote 4.x DiarizeOutput wrapping a fake Annotation."""
    ann = MagicMock()

    def _itertracks(yield_label: bool = True):
        for s, e, lab in turns:
            seg = MagicMock(start=s, end=e)
            yield seg, None, lab

    ann.itertracks.side_effect = _itertracks
    # 4.x: pipeline returns DiarizeOutput with .speaker_diarization = Annotation
    wrapper = MagicMock()
    wrapper.speaker_diarization = ann
    return wrapper


def test_diarize_returns_speaker_turns(tmp_path: Path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"fake")

    pipeline = MagicMock()
    pipeline.return_value = _fake_annotation(
        [(0.0, 1.5, "SPEAKER_00"), (1.5, 3.0, "SPEAKER_01")]
    )

    with patch(
        "pyannote.audio.Pipeline.from_pretrained", return_value=pipeline
    ), _patch_sf_read():
        diarizer = PyannoteDiarizer(hf_token="hf_test", backend="cpu")
        turns = diarizer.diarize(wav, num_speakers=None)

    assert len(turns) == 2
    assert isinstance(turns[0], SpeakerTurn)
    assert turns[0].speaker_id == "SPEAKER_00"
    assert turns[1].speaker_id == "SPEAKER_01"
    # Pipeline must be called with a {waveform, sample_rate} dict, not a path
    arg = pipeline.call_args.args[0]
    assert isinstance(arg, dict) and {"waveform", "sample_rate"} <= arg.keys()


def test_diarize_passes_num_speakers_hint(tmp_path: Path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"fake")
    pipeline = MagicMock()
    pipeline.return_value = _fake_annotation([])

    with patch(
        "pyannote.audio.Pipeline.from_pretrained", return_value=pipeline
    ), _patch_sf_read():
        diarizer = PyannoteDiarizer(hf_token="hf_test", backend="cpu")
        diarizer.diarize(wav, num_speakers=3)

    assert pipeline.call_args.kwargs.get("num_speakers") == 3


def test_backend_sets_torch_device():
    pipeline = MagicMock()
    with (
        patch(
            "pyannote.audio.Pipeline.from_pretrained", return_value=pipeline
        ),
        patch("torch.device", return_value="fake-device") as torch_device_mock,
    ):
        PyannoteDiarizer(hf_token="hf_test", backend="cuda")
        torch_device_mock.assert_called_with("cuda")
        pipeline.to.assert_called_with("fake-device")
