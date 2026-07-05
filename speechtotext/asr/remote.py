from __future__ import annotations

import io
import math
import threading
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

from speechtotext.models import Segment
from speechtotext.pipeline import CancelledError

# Remote OpenAI-compatible /audio/transcriptions endpoints (FastFlowLM,
# Lemonade Server) return plain text with no timestamps, but the speaker
# merge needs per-segment times. The file is therefore split on silences
# into bounded chunks and each chunk transcribed separately; the chunk
# bounds become the segment timestamps. Coarser than faster-whisper's
# native segments, but silences are where speaker changes happen, so
# overlap-based speaker assignment stays usable.
_FRAME_SECONDS = 0.02
_MIN_SILENCE_SECONDS = 0.4
_MAX_CHUNK_SECONDS = 60.0
# Below this, treat energy as silence even in quiet recordings.
_SILENCE_FLOOR = 1e-4


def _split_on_silence(
    samples: np.ndarray,
    sample_rate: int,
    max_chunk_seconds: float = _MAX_CHUNK_SECONDS,
    min_silence_seconds: float = _MIN_SILENCE_SECONDS,
) -> list[tuple[float, float]]:
    """Split mono audio into (start, end) second-ranges covering the file.

    Cut points are the centres of silent runs >= min_silence_seconds; any
    resulting chunk longer than max_chunk_seconds is split evenly. The
    returned ranges tile the whole file with no gaps or overlap.
    """
    n = len(samples)
    if n == 0:
        return []

    frame = max(1, int(sample_rate * _FRAME_SECONDS))
    n_frames = math.ceil(n / frame)
    padded = np.pad(samples.astype(np.float64), (0, n_frames * frame - n))
    rms = np.sqrt(np.mean(padded.reshape(n_frames, frame) ** 2, axis=1))
    threshold = max(_SILENCE_FLOOR, 0.1 * float(np.percentile(rms, 95)))
    silent = rms < threshold

    min_run = max(1, int(min_silence_seconds / _FRAME_SECONDS))
    cut_times: list[float] = []
    i = 0
    while i < n_frames:
        if silent[i]:
            j = i
            while j < n_frames and silent[j]:
                j += 1
            if j - i >= min_run:
                cut_times.append(((i + j) / 2) * frame / sample_rate)
            i = j
        else:
            i += 1

    duration = n / sample_rate
    bounds = [0.0, *cut_times, duration]
    out: list[tuple[float, float]] = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a <= 1e-6:
            continue
        pieces = max(1, math.ceil((b - a) / max_chunk_seconds))
        step = (b - a) / pieces
        for m in range(pieces):
            out.append((a + m * step, min(b, a + (m + 1) * step)))
    return out


class RemoteWhisperASR:
    """ASR via an OpenAI-compatible /audio/transcriptions HTTP endpoint.

    Works against FastFlowLM (`flm serve --asr 1`, NPU) and Lemonade
    Server. The endpoint returns text only; see module docstring for how
    timestamps are reconstructed.
    """

    def __init__(
        self,
        base_url: str,
        model: str = "whisper-v3",
        timeout_seconds: float = 600.0,
        transport=None,
    ) -> None:
        try:
            import httpx  # noqa: F401  lazy: only the remote engine needs it
        except ImportError as exc:
            raise RuntimeError(
                "asr_engine = \"remote\" requires httpx; install with "
                "pip install 'speechtotext[api]'"
            ) from exc
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._transport = transport
        self.label = f"remote-whisper:{model}"

    def transcribe(
        self,
        wav_path: Path,
        language: str | None,
        on_progress: Callable[[float], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[Segment]:
        import httpx

        data, sample_rate = sf.read(str(wav_path), dtype="float32", always_2d=True)
        mono = data.mean(axis=1)
        duration = len(mono) / sample_rate
        chunks = _split_on_silence(mono, sample_rate)

        url = f"{self._base_url}/audio/transcriptions"
        segments: list[Segment] = []
        with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
            for start, end in chunks:
                if cancel_event is not None and cancel_event.is_set():
                    raise CancelledError("transcription cancelled")
                buf = io.BytesIO()
                sf.write(
                    buf,
                    mono[int(start * sample_rate) : int(end * sample_rate)],
                    sample_rate,
                    format="WAV",
                    subtype="PCM_16",
                )
                buf.seek(0)
                form = {"model": self._model}
                if language:
                    form["language"] = language
                try:
                    resp = client.post(
                        url,
                        data=form,
                        files={"file": ("chunk.wav", buf, "audio/wav")},
                    )
                except httpx.HTTPError as exc:
                    raise RuntimeError(
                        f"remote ASR request to {url} failed: {exc}. "
                        "Is the FastFlowLM/Lemonade server running?"
                    ) from exc
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"remote ASR error {resp.status_code}: {resp.text[:200]}"
                    )
                text = str(resp.json().get("text", "")).strip()
                if text:
                    segments.append(
                        Segment(start=start, end=end, text=text, language=language)
                    )
                if on_progress is not None and duration > 0:
                    on_progress(min(1.0, end / duration))
        return segments
