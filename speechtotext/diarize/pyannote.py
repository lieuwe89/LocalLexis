from __future__ import annotations

from pathlib import Path
from typing import Literal

import torch
from pyannote.audio import Pipeline

from speechtotext.models import SpeakerTurn

_MODEL_ID = "pyannote/speaker-diarization-3.1"  # 4.0 endpoint: update when stable URL known


class PyannoteDiarizer:
    def __init__(
        self,
        hf_token: str,
        backend: Literal["cpu", "cuda", "mps"] = "cpu",
        model_id: str = _MODEL_ID,
    ) -> None:
        if not hf_token:
            raise ValueError("pyannote requires a Hugging Face access token")
        self._pipeline = Pipeline.from_pretrained(model_id, use_auth_token=hf_token)
        device = torch.device(backend)
        self._pipeline.to(device)

    def diarize(self, wav_path: Path, num_speakers: int | None) -> list[SpeakerTurn]:
        kwargs: dict = {}
        if num_speakers is not None:
            kwargs["num_speakers"] = num_speakers
        annotation = self._pipeline(str(wav_path), **kwargs)
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
