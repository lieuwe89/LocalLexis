from __future__ import annotations

from pathlib import Path
from typing import Literal

from speechtotext.models import SpeakerTurn

_MODEL_ID = "pyannote/speaker-diarization-3.1"  # 4.0 endpoint: update when stable URL known


class PyannoteDiarizer:
    def __init__(
        self,
        hf_token: str,
        backend: Literal["cpu", "cuda", "mps"] = "cpu",
        model_id: str = _MODEL_ID,
    ) -> None:
        import torch  # lazy: deferred from module load to first instantiation
        from pyannote.audio import Pipeline  # lazy: deferred from module load to first instantiation

        self._torch = torch
        if not hf_token:
            raise ValueError("pyannote requires a Hugging Face access token")
        # pyannote 4.x renamed `use_auth_token` -> `token`. Pass both names so
        # 3.x and 4.x both work; whichever the installed version accepts wins.
        try:
            self._pipeline = Pipeline.from_pretrained(model_id, token=hf_token)
        except TypeError:
            self._pipeline = Pipeline.from_pretrained(model_id, use_auth_token=hf_token)
        device = torch.device(backend)
        self._pipeline.to(device)

    def diarize(self, wav_path: Path, num_speakers: int | None) -> list[SpeakerTurn]:
        import soundfile as sf  # lazy: deferred from module load to first diarize call

        kwargs: dict = {}
        if num_speakers is not None:
            kwargs["num_speakers"] = num_speakers
        # Pre-load with soundfile so pyannote doesn't reach for torchcodec,
        # whose C extensions are not always loadable from the PyInstaller
        # frozen bundle. pyannote accepts {"waveform": Tensor, "sample_rate": int}.
        data, sample_rate = sf.read(str(wav_path), always_2d=True, dtype="float32")
        # soundfile returns (time, channel); pyannote wants (channel, time).
        waveform = self._torch.from_numpy(data.T)
        result = self._pipeline(
            {"waveform": waveform, "sample_rate": sample_rate}, **kwargs
        )
        # pyannote 4.x returns a DiarizeOutput wrapping the Annotation;
        # 3.x returns the Annotation directly.
        annotation = getattr(result, "speaker_diarization", result)
        turns: list[SpeakerTurn] = []
        for segment, _track, label in annotation.itertracks(yield_label=True):
            turns.append(
                SpeakerTurn(
                    start=float(segment.start),
                    end=float(segment.end),
                    speaker_id=str(label),
                )
            )
        return turns
