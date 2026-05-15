from pathlib import Path
from unittest.mock import MagicMock, patch

from speechtotext.diarize.pyannote import PyannoteDiarizer
from speechtotext.models import SpeakerTurn


def _fake_annotation(turns: list[tuple[float, float, str]]):
    ann = MagicMock()

    def _itertracks(yield_label: bool = True):
        for s, e, lab in turns:
            seg = MagicMock(start=s, end=e)
            yield seg, None, lab

    ann.itertracks.side_effect = _itertracks
    return ann


def test_diarize_returns_speaker_turns(tmp_path: Path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"fake")

    pipeline = MagicMock()
    pipeline.return_value = _fake_annotation(
        [(0.0, 1.5, "SPEAKER_00"), (1.5, 3.0, "SPEAKER_01")]
    )

    with patch(
        "speechtotext.diarize.pyannote.Pipeline.from_pretrained", return_value=pipeline
    ):
        diarizer = PyannoteDiarizer(hf_token="hf_test", backend="cpu")
        turns = diarizer.diarize(wav, num_speakers=None)

    assert len(turns) == 2
    assert isinstance(turns[0], SpeakerTurn)
    assert turns[0].speaker_id == "SPEAKER_00"
    assert turns[1].speaker_id == "SPEAKER_01"


def test_diarize_passes_num_speakers_hint(tmp_path: Path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"fake")
    pipeline = MagicMock()
    pipeline.return_value = _fake_annotation([])

    with patch(
        "speechtotext.diarize.pyannote.Pipeline.from_pretrained", return_value=pipeline
    ):
        diarizer = PyannoteDiarizer(hf_token="hf_test", backend="cpu")
        diarizer.diarize(wav, num_speakers=3)

    assert pipeline.call_args.kwargs.get("num_speakers") == 3


def test_backend_sets_torch_device():
    pipeline = MagicMock()
    with (
        patch(
            "speechtotext.diarize.pyannote.Pipeline.from_pretrained", return_value=pipeline
        ),
        patch("speechtotext.diarize.pyannote.torch") as torch_mod,
    ):
        torch_mod.device.return_value = "fake-device"
        PyannoteDiarizer(hf_token="hf_test", backend="cuda")
        torch_mod.device.assert_called_with("cuda")
        pipeline.to.assert_called_with("fake-device")
