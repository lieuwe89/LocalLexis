from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from speechtotext.asr.base import ASRBackend
    from speechtotext.config import Config


def build_asr(cfg: "Config", backend: str) -> "ASRBackend":
    """Construct the ASR backend selected by cfg.asr_engine.

    "local" runs faster-whisper in-process on cpu/cuda/mps; "remote" calls
    an OpenAI-compatible /audio/transcriptions endpoint (FastFlowLM NPU,
    Lemonade Server) and ignores the compute backend.
    """
    if cfg.asr_engine == "remote":
        from speechtotext.asr.remote import RemoteWhisperASR

        return RemoteWhisperASR(
            base_url=cfg.remote_asr_url, model=cfg.remote_asr_model
        )
    from speechtotext.asr.faster_whisper import FasterWhisperASR

    return FasterWhisperASR(
        model_size=cfg.asr_model,
        backend=backend,  # type: ignore[arg-type]
        download_root=cfg.model_cache_dir,
        cpu_threads=cfg.asr_cpu_threads,
    )
