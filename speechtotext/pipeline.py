from __future__ import annotations

import inspect
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from speechtotext.asr.base import ASRBackend
from speechtotext.config import Config
from speechtotext.diarize.base import DiarizerBackend
from speechtotext.ingest.file import normalize_to_wav
from speechtotext.merger import merge
from speechtotext.models import ProgressEvent, Transcript

ProgressCallback = Callable[[ProgressEvent], None]


class CancelledError(Exception):
    pass


def _noop(_: ProgressEvent) -> None:
    pass


class Pipeline:
    def __init__(
        self,
        config: Config,
        asr: ASRBackend,
        diarizer: DiarizerBackend,
        resolved_backend: str,
    ) -> None:
        self._config = config
        self._asr = asr
        self._diarizer = diarizer
        self._backend = resolved_backend

    def run(
        self,
        audio: Path,
        language: str | None = None,
        num_speakers: int | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Transcript:
        emit = on_progress or _noop

        def check_cancel() -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError("cancelled")

        tmp_dir = Path(tempfile.gettempdir()) / "speechtotext"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_wav = tmp_dir / f"{uuid.uuid4().hex}.wav"
        wav: Path | None = None

        try:
            check_cancel()
            emit(ProgressEvent("ingest", 0.0, f"normalizing {audio.name}"))
            wav = normalize_to_wav(audio, tmp_wav)
            emit(ProgressEvent("ingest", 1.0, "normalized"))

            check_cancel()
            emit(ProgressEvent("asr", 0.0, "transcribing"))
            asr_kwargs: dict = {"language": language}
            sig = inspect.signature(self._asr.transcribe)
            if "on_progress" in sig.parameters:
                asr_kwargs["on_progress"] = lambda pct: emit(ProgressEvent("asr", pct, "transcribing"))
            if "cancel_event" in sig.parameters:
                asr_kwargs["cancel_event"] = cancel_event
            segments = self._asr.transcribe(wav, **asr_kwargs)
            detected_language = segments[0].language if segments else (language or "unknown")
            emit(ProgressEvent("asr", 1.0, f"{len(segments)} segments"))

            check_cancel()
            emit(ProgressEvent("diarize", 0.0, "diarizing"))
            turns = self._diarizer.diarize(wav, num_speakers=num_speakers)
            emit(ProgressEvent("diarize", 1.0, f"{len(turns)} turns"))

            check_cancel()
            emit(ProgressEvent("merge", 0.0, "aligning speakers"))
            labeled = merge(segments, turns)
            speaker_ids = sorted({s.speaker_id for s in labeled if s.speaker_id != "UNKNOWN"})
            speakers = {sid: f"Speaker {i + 1}" for i, sid in enumerate(speaker_ids)}
            emit(ProgressEvent("merge", 1.0, f"{len(speakers)} speakers"))

            duration = max((s.end for s in labeled), default=0.0)
            transcript = Transcript(
                audio_path=audio,
                duration_seconds=duration,
                language=detected_language or "unknown",
                speakers=speakers,
                segments=labeled,
                models={
                    "asr": getattr(
                        self._asr, "label", f"faster-whisper:{self._config.asr_model}"
                    ),
                    "diarizer": "pyannote:4.0",
                    "backend": self._backend,
                },
                created_at=datetime.now(timezone.utc),
            )
            return transcript
        finally:
            try:
                if wav is not None and wav.exists():
                    wav.unlink()
            except OSError:
                pass
