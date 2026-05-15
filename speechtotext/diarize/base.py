from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from speechtotext.models import SpeakerTurn


@runtime_checkable
class DiarizerBackend(Protocol):
    def diarize(self, wav_path: Path, num_speakers: int | None) -> list[SpeakerTurn]: ...
