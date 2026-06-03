from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable, Literal

from speechtotext.models import Segment


def _resolve_bundled_model(name: str) -> str | None:
    """Look for a bundled faster-whisper model dir matching `name`.

    Searched env var `LOCALLEXIS_BUNDLED_MODELS` (set by the Tauri shell) for
    a subdirectory named `faster-whisper-<name>`. Returns its absolute path if
    it contains a model.bin, else None.
    """
    root = os.environ.get("LOCALLEXIS_BUNDLED_MODELS")
    if not root:
        return None
    candidate = Path(root) / f"faster-whisper-{name}"
    if (candidate / "model.bin").is_file():
        return str(candidate)
    return None

_DEVICE_MAP: dict[str, tuple[str, str]] = {
    "cpu": ("cpu", "int8"),
    "cuda": ("cuda", "float16"),
    "mps": ("cpu", "int8"),  # CTranslate2 has no native MPS; CPU on Apple Silicon
}


class CancelledError(Exception):
    pass


class FasterWhisperASR:
    def __init__(
        self,
        model_size: str = "base.en",
        backend: Literal["cpu", "cuda", "mps"] = "cpu",
        download_root: Path | None = None,
    ) -> None:
        from faster_whisper import WhisperModel  # lazy: deferred from module load to first instantiation

        device, compute_type = _DEVICE_MAP[backend]
        bundled = _resolve_bundled_model(model_size)
        self._model = WhisperModel(
            model_size_or_path=bundled or model_size,
            device=device,
            compute_type=compute_type,
            download_root=None if bundled else (str(download_root) if download_root else None),
        )

    def transcribe(
        self,
        wav_path: Path,
        language: str | None,
        on_progress: Callable[[float], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[Segment]:
        segments_iter, info = self._model.transcribe(
            str(wav_path),
            language=language,
            beam_size=5,
            # Anti-loop safety net. A *scalar* temperature disables faster-whisper's
            # temperature fallback; a list re-enables it. When a 30s window decodes
            # too-repetitively (compression_ratio_threshold) or with low confidence
            # (log_prob_threshold), decoding retries at a higher temperature and —
            # via prompt_reset_on_temperature — drops the conditioning prompt. That
            # breaks the feedback loop that otherwise causes runaway repetition on
            # long / low-SNR / multi-speaker audio, while temp 0 keeps quality.
            temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            # Keep cross-window coherence (consistent spelling/terminology), but...
            condition_on_previous_text=True,
            # ...reset the prompt during fallback so a bad window can't poison the rest.
            prompt_reset_on_temperature=0.5,
            # Hard guard: never emit the same 3-gram back-to-back (kills loops at source).
            no_repeat_ngram_size=3,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
            vad_filter=True,
        )
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        out: list[Segment] = []
        for s in segments_iter:
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError("transcription cancelled")
            out.append(
                Segment(
                    start=float(s.start),
                    end=float(s.end),
                    text=s.text.strip(),
                    language=info.language,
                )
            )
            if on_progress and duration > 0:
                pct = min(1.0, float(s.end) / duration)
                on_progress(pct)
        return out
