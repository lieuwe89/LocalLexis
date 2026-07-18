from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from speechtotext.api.events import (
    CompleteEvent,
    ErrorEvent,
    LineEvent,
    StageEvent,
)
from speechtotext.api.jobs import JobRegistry
from speechtotext.asr import build_asr
from speechtotext.backend import resolve_backend
from speechtotext.config import Config, DEFAULT_CONFIG_PATH, load_config
from speechtotext.diarize.pyannote import PyannoteDiarizer
from speechtotext.ingest.mic import record_to_file
from speechtotext.models import ProgressEvent, Transcript
from speechtotext.pipeline import CancelledError, Pipeline
from speechtotext.api.workspace import get_workspace_id
from speechtotext.rag import embedder as rag_embedder
from speechtotext.summarize.prompt import (
    TranscriptTooLongError,
    build_ask_messages,
    build_summary_messages,
    check_within_budget,
)
from speechtotext.summarize.provider import ProviderError, provider_from_config
from speechtotext.writer import write_transcript


# Number of top-scoring chunks retrieved for a library-wide ask job.
ASK_TOP_K = 8


def _max_concurrent_transcribe() -> int:
    raw = os.environ.get("LOCALLEXIS_MAX_CONCURRENT_TRANSCRIBE")
    if raw is None:
        return 1
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


# Global cap on simultaneous transcription jobs. Each job loads ASR +
# diarization models, so launching several at once (e.g. six files dropped
# into a watched folder together) exhausts RAM/GPU memory and crashes the
# sidecar. Jobs past the cap wait in their own thread before loading models.
_TRANSCRIBE_SEM = threading.BoundedSemaphore(_max_concurrent_transcribe())


def _build_pipeline(cfg: Config, cli_backend: str | None) -> tuple[Pipeline, str]:
    backend = resolve_backend(cli_flag=cli_backend, config=cfg)
    asr = build_asr(cfg, backend)
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
    cancel = threading.Event()
    _CANCEL_EVENTS[job_id] = cancel

    def _work() -> None:
        acquired = False
        try:
            # Bound concurrent model-loading jobs. Try immediately; if the
            # slot is taken, surface a 'queued' stage and wait for a slot,
            # honouring cancellation while blocked.
            if not _TRANSCRIBE_SEM.acquire(blocking=False):
                emit(StageEvent(stage="queued", percent=0.0))
                while not _TRANSCRIBE_SEM.acquire(timeout=0.5):
                    if cancel.is_set():
                        emit(ErrorEvent(message="cancelled"))
                        return
            acquired = True
            emit(StageEvent(stage="load", percent=0.0))
            cfg = load_config(config_path=config_path)
            pipeline, _resolved = _build_pipeline(cfg, backend)
            emit(StageEvent(stage="load", percent=1.0))
            transcript: Transcript = pipeline.run(
                audio,
                language=None if language in (None, "auto") else language,
                num_speakers=num_speakers,
                on_progress=_bridge_progress(emit),
                cancel_event=cancel,
            )
            emit(StageEvent(stage="write", percent=0.0))
            # Stamp the hub's workspace_id into the JSON so synced
            # devices can attribute the transcript to this workspace.
            txt, json_path = write_transcript(
                transcript, workspace_id=get_workspace_id()
            )
            for seg in transcript.segments:
                emit(LineEvent(speaker=seg.speaker_id, ts=seg.start, text=seg.text))
            emit(CompleteEvent(
                transcript_id=audio.stem,
                paths={"txt": str(txt), "json": str(json_path)},
            ))
        except CancelledError:
            emit(ErrorEvent(message="cancelled"))
        except Exception as exc:  # noqa: BLE001
            emit(ErrorEvent(message=f"{type(exc).__name__}: {exc}"))
        finally:
            if acquired:
                _TRANSCRIBE_SEM.release()
            _CANCEL_EVENTS.pop(job_id, None)
            if _own_loop:
                loop.call_soon_threadsafe(loop.stop)

    threading.Thread(target=_work, daemon=True).start()
    if _own_loop:
        threading.Thread(target=lambda: (loop.run_forever(), loop.close()), daemon=True).start()


_STOP_EVENTS: dict[str, threading.Event] = {}
_CANCEL_EVENTS: dict[str, threading.Event] = {}


def cancel_transcribe_job(job_id: str) -> bool:
    ev = _CANCEL_EVENTS.get(job_id)
    if ev is None:
        return False
    ev.set()
    return True


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
            record_to_file(out_path, device=device, stop_event=stop)
            emit(StageEvent(stage="record", percent=1.0))
            emit(CompleteEvent(
                transcript_id="",
                paths={"audio": str(out_path)},
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


def _summarize_provider(cfg):
    """Indirection point so tests can patch the provider construction."""
    return provider_from_config(cfg.summarize)


def run_summarize_job(
    registry: JobRegistry,
    job_id: str,
    json_path: Path,
    write_lock: threading.Lock,
    on_written=None,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> None:
    """Summarize a transcript with the configured LLM provider.

    `write_lock` is the per-transcript lock from routes_transcripts so a
    concurrent CRDT PATCH can't interleave with our read-modify-write.
    `on_written(json_path)` reindexes the library row after the write.
    """
    try:
        loop = asyncio.get_running_loop()
        _own_loop = False
    except RuntimeError:
        loop = asyncio.new_event_loop()
        _own_loop = True

    emit = _make_emit(loop, registry, job_id)

    def _work() -> None:
        try:
            emit(StageEvent(stage="summarize", percent=0.0))
            cfg = load_config(config_path=config_path)
            provider = _summarize_provider(cfg)
            doc = json.loads(json_path.read_text(encoding="utf-8"))
            messages = build_summary_messages(doc)
            check_within_budget(messages)
            summary = provider.chat(messages)
            emit(StageEvent(stage="summarize", percent=0.9))
            with write_lock:
                # Re-read under the lock: a CRDT PATCH may have landed
                # while the provider was thinking.
                doc = json.loads(json_path.read_text(encoding="utf-8"))
                doc["summary"] = summary
                doc["summary_meta"] = {
                    "provider": cfg.summarize.provider,
                    "model": provider.model,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                content = json.dumps(doc, indent=2, ensure_ascii=False)
                tmp = json_path.with_suffix(json_path.suffix + ".tmp")
                tmp.write_text(content, encoding="utf-8")
                os.replace(tmp, json_path)
            if on_written:
                on_written(json_path)
            emit(CompleteEvent(
                transcript_id=json_path.stem,
                paths={"json": str(json_path)},
            ))
        except ProviderError as exc:
            emit(ErrorEvent(message=str(exc)))
        except TranscriptTooLongError as exc:
            emit(ErrorEvent(message=str(exc)))
        except Exception as exc:  # noqa: BLE001
            emit(ErrorEvent(message=f"{type(exc).__name__}: {exc}"))
        finally:
            if _own_loop:
                loop.call_soon_threadsafe(loop.stop)

    threading.Thread(target=_work, daemon=True).start()
    if _own_loop:
        threading.Thread(target=lambda: (loop.run_forever(), loop.close()), daemon=True).start()


def run_ask_job(
    registry: JobRegistry,
    job_id: str,
    question: str,
    db,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> None:
    """Answer a question over the whole library (RAG).

    Retrieves the top chunks by embedding similarity, asks the configured
    LLM provider, and stores {answer, sources} on the JobRecord.
    """
    try:
        loop = asyncio.get_running_loop()
        _own_loop = False
    except RuntimeError:
        loop = asyncio.new_event_loop()
        _own_loop = True

    emit = _make_emit(loop, registry, job_id)

    def _work() -> None:
        try:
            emit(StageEvent(stage="retrieve", percent=0.0))
            qvec = rag_embedder.get_embedder().embed([question])[0]
            chunks = db.top_chunks(qvec, rag_embedder.EMBED_MODEL, k=ASK_TOP_K)
            if not chunks:
                emit(ErrorEvent(message=(
                    "nothing retrieved — the semantic index may still be "
                    "building, or the library is empty"
                )))
                return
            emit(StageEvent(stage="ask", percent=0.3))
            cfg = load_config(config_path=config_path)
            provider = _summarize_provider(cfg)
            answer = provider.chat(build_ask_messages(question, chunks))
            registry.get(job_id).result = {
                "answer": answer,
                "sources": [
                    {
                        "transcript_id": c["transcript_id"],
                        "segment_index": c["first_segment"],
                        "start": c["start"],
                    }
                    for c in chunks
                ],
            }
            emit(CompleteEvent())
        except (ProviderError, rag_embedder.EmbedderError) as exc:
            emit(ErrorEvent(message=str(exc)))
        except Exception as exc:  # noqa: BLE001
            emit(ErrorEvent(message=f"{type(exc).__name__}: {exc}"))
        finally:
            if _own_loop:
                loop.call_soon_threadsafe(loop.stop)

    threading.Thread(target=_work, daemon=True).start()
    if _own_loop:
        threading.Thread(target=lambda: (loop.run_forever(), loop.close()), daemon=True).start()
