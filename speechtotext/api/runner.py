from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from speechtotext.api.events import (
    CompleteEvent,
    ErrorEvent,
    LineEvent,
    StageEvent,
)
from speechtotext.api.jobs import JobRegistry
from speechtotext.asr.faster_whisper import FasterWhisperASR
from speechtotext.backend import resolve_backend
from speechtotext.config import Config, DEFAULT_CONFIG_PATH, load_config
from speechtotext.diarize.pyannote import PyannoteDiarizer
from speechtotext.ingest.mic import record_to_wav
from speechtotext.models import ProgressEvent, Transcript
from speechtotext.pipeline import Pipeline
from speechtotext.writer import write_transcript


def _build_pipeline(cfg: Config, cli_backend: str | None) -> tuple[Pipeline, str]:
    backend = resolve_backend(cli_flag=cli_backend, config=cfg)
    asr = FasterWhisperASR(
        model_size=cfg.asr_model, backend=backend, download_root=cfg.model_cache_dir
    )
    if not cfg.hf_token:
        raise RuntimeError("hf_token not set; configure via /config or config.toml")
    diarizer = PyannoteDiarizer(hf_token=cfg.hf_token, backend=backend)
    return Pipeline(config=cfg, asr=asr, diarizer=diarizer, resolved_backend=backend), backend


def _make_emit(loop: asyncio.AbstractEventLoop, registry: JobRegistry, job_id: str):
    def emit(event):
        asyncio.run_coroutine_threadsafe(registry.publish(job_id, event), loop).result(timeout=5.0)
    return emit


def _bridge_progress(emit) -> "callable":
    def on_progress(pe: ProgressEvent) -> None:
        emit(StageEvent(stage=pe.stage, percent=pe.pct))
    return on_progress


def run_transcribe_job(
    registry: JobRegistry,
    job_id: str,
    audio: Path,
    language: str | None = None,
    num_speakers: int | None = None,
    backend: str | None = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> None:
    try:
        loop = asyncio.get_running_loop()
        _own_loop = False
    except RuntimeError:
        loop = asyncio.new_event_loop()
        _own_loop = True

    emit = _make_emit(loop, registry, job_id)

    def _work() -> None:
        try:
            cfg = load_config(config_path=config_path)
            pipeline, _resolved = _build_pipeline(cfg, backend)
            transcript: Transcript = pipeline.run(
                audio,
                language=None if language in (None, "auto") else language,
                num_speakers=num_speakers,
                on_progress=_bridge_progress(emit),
            )
            emit(StageEvent(stage="write", percent=0.0))
            txt, json_path = write_transcript(transcript)
            for seg in transcript.segments:
                emit(LineEvent(speaker=seg.speaker_id, ts=seg.start, text=seg.text))
            emit(CompleteEvent(
                transcript_id=audio.stem,
                paths={"txt": str(txt), "json": str(json_path)},
            ))
        except Exception as exc:  # noqa: BLE001
            emit(ErrorEvent(message=f"{type(exc).__name__}: {exc}"))
        finally:
            if _own_loop:
                loop.call_soon_threadsafe(loop.stop)

    threading.Thread(target=_work, daemon=True).start()
    if _own_loop:
        threading.Thread(target=lambda: (loop.run_forever(), loop.close()), daemon=True).start()


_STOP_EVENTS: dict[str, threading.Event] = {}


def run_record_job(
    registry: JobRegistry,
    job_id: str,
    out_path: Path,
    device: str | None = None,
) -> None:
    try:
        loop = asyncio.get_running_loop()
        _own_loop = False
    except RuntimeError:
        loop = asyncio.new_event_loop()
        _own_loop = True

    emit = _make_emit(loop, registry, job_id)
    stop = threading.Event()
    _STOP_EVENTS[job_id] = stop

    def _work() -> None:
        try:
            emit(StageEvent(stage="record", percent=0.0))
            record_to_wav(out_path, device=device, stop_event=stop)
            emit(StageEvent(stage="record", percent=1.0))
            emit(CompleteEvent(
                transcript_id="",
                paths={"wav": str(out_path)},
            ))
        except Exception as exc:  # noqa: BLE001
            emit(ErrorEvent(message=f"{type(exc).__name__}: {exc}"))
        finally:
            _STOP_EVENTS.pop(job_id, None)
            if _own_loop:
                loop.call_soon_threadsafe(loop.stop)

    threading.Thread(target=_work, daemon=True).start()
    if _own_loop:
        threading.Thread(target=lambda: (loop.run_forever(), loop.close()), daemon=True).start()


def stop_record_job(job_id: str) -> bool:
    ev = _STOP_EVENTS.get(job_id)
    if ev is None:
        return False
    ev.set()
    return True
