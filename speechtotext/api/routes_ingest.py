"""Audio ingest endpoints for paired LAN devices.

``/jobs/upload`` accepts a complete signed audio file. The body is
streamed through a single SHA-256 + tee-to-temp-file pass so meeting-
length recordings do not need to be buffered in RAM, then the device
signature is verified against the computed digest. On verify failure
the temp file is deleted; on success it is renamed into place and a
transcription job is dispatched.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from speechtotext.api import library_db as library_db_module
from speechtotext.api.auth import verify_device_signature_with_digest

router = APIRouter()
DEFAULT_MAX_UPLOAD_BYTES = 256 * 1024 * 1024
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,179}$")


class UploadResponse(BaseModel):
    job_id: str
    bytes_received: int = Field(ge=1)


def _incoming_dir(request: Request) -> Path:
    configured = getattr(request.app.state, "incoming_dir", None)
    if configured is not None:
        return Path(configured)
    return library_db_module.default_app_data_dir() / "incoming"


def _safe_filename(filename: str | None) -> str:
    if filename is None or not filename.strip():
        return "upload.wav"
    name = filename.strip()
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise HTTPException(
            status_code=400, detail="filename must be a simple basename"
        )
    if not _SAFE_FILENAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=400,
            detail=(
                "filename must contain only letters, numbers, dot, dash, "
                "or underscore"
            ),
        )
    return name


def _unique_upload_path(root: Path, filename: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    suffix = secrets.token_hex(4)
    return root / f"{stamp}-{suffix}-{filename}"


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def sweep_partial_uploads(incoming_dir: Path) -> int:
    """Delete any leftover ``*.partial`` files under ``incoming_dir``.

    Called at app startup so a crash mid-stream cannot leave indefinite
    scratch files behind.
    """
    if not incoming_dir.exists():
        return 0
    removed = 0
    for partial in incoming_dir.glob("*.partial"):
        try:
            partial.unlink()
            removed += 1
        except OSError:
            pass

    # Abandoned import stages: client died between stage and commit.
    cutoff = time.time() - 24 * 3600
    for staged in incoming_dir.glob("*.import"):
        try:
            if staged.stat().st_mtime < cutoff:
                staged.unlink()
                removed += 1
        except OSError:
            pass
    return removed


async def _receive_signed_body(
    request: Request, incoming: Path, max_bytes: int
) -> tuple[Path, int, str]:
    """Stream the signed request body to a temp file, verify its signature.

    Cheap header checks first (Content-Length present + within limit), then
    stream the body through SHA-256 + tee to ``<incoming>/<random>.partial``,
    capping at ``max_bytes``, then verify the device signature against the
    computed digest. On any failure the temp file is deleted and an
    HTTPException is raised. Returns ``(temp_path, bytes_seen, device_id)``
    on success — caller is responsible for renaming/cleaning up the temp file.
    """
    raw_length = request.headers.get("content-length")
    if raw_length is None:
        raise HTTPException(status_code=411, detail="Content-Length required")
    try:
        content_length = int(raw_length)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="invalid Content-Length"
        ) from exc
    if content_length > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"audio upload exceeds {max_bytes} byte limit",
        )

    temp_path = incoming / f"{secrets.token_hex(8)}.partial"

    hasher = hashlib.sha256()
    bytes_seen = 0
    try:
        with temp_path.open("wb") as fh:
            async for chunk in request.stream():
                if not chunk:
                    continue
                bytes_seen += len(chunk)
                if bytes_seen > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"audio upload exceeds {max_bytes} byte limit",
                    )
                hasher.update(chunk)
                fh.write(chunk)
    except HTTPException:
        _unlink_quietly(temp_path)
        raise
    except Exception:
        _unlink_quietly(temp_path)
        raise

    if bytes_seen == 0:
        _unlink_quietly(temp_path)
        raise HTTPException(
            status_code=400, detail="audio upload body cannot be empty"
        )

    try:
        device_id = await verify_device_signature_with_digest(
            request, hasher.digest()
        )
    except HTTPException:
        _unlink_quietly(temp_path)
        raise

    return temp_path, bytes_seen, device_id


@router.post("/jobs/upload", status_code=202, response_model=UploadResponse)
async def post_upload(
    request: Request,
    filename: str | None = Query(default=None, max_length=180),
) -> UploadResponse:
    """Accept a streaming signed audio upload, verify, dispatch transcription.

    Flow:
      1. Cheap header checks (Content-Length present + within limit).
      2. Stream body through SHA-256 + tee to ``<incoming>/<random>.partial``,
         capping at ``max_upload_bytes``.
      3. Verify signature against the computed digest. On failure delete
         temp + raise 401.
      4. ``os.replace`` temp → final dest. Dispatch transcription.
    """
    max_bytes = int(
        getattr(request.app.state, "max_upload_bytes", DEFAULT_MAX_UPLOAD_BYTES)
    )
    safe_name = _safe_filename(filename)
    incoming = _incoming_dir(request)
    incoming.mkdir(parents=True, exist_ok=True)

    temp_path, bytes_seen, device_id = await _receive_signed_body(
        request, incoming, max_bytes
    )

    audio_path = _unique_upload_path(incoming, safe_name)
    try:
        os.replace(temp_path, audio_path)
    except OSError as exc:
        _unlink_quietly(temp_path)
        raise HTTPException(
            status_code=500, detail=f"failed to store upload: {exc}"
        ) from exc

    registry = request.app.state.jobs
    job_id = registry.create(
        kind="transcribe", audio_path=str(audio_path), device_id=device_id
    )

    from speechtotext.api import runner

    try:
        runner.run_transcribe_job(registry, job_id, audio_path)
    except Exception as exc:
        _unlink_quietly(audio_path)
        raise HTTPException(
            status_code=500,
            detail=(
                "failed to dispatch upload job: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc

    return UploadResponse(job_id=job_id, bytes_received=bytes_seen)


@router.post("/transcripts/import/audio")
async def post_import_audio(
    request: Request,
    filename: str | None = Query(default=None, max_length=180),
) -> dict:
    """Stage audio for a transcript import (no transcription job).

    The staged file is named ``<token>.import``: never indexed by the
    library walker (not ``.json``) and recognizable for stale-cleanup at
    startup.
    """
    max_bytes = int(
        getattr(request.app.state, "max_upload_bytes", DEFAULT_MAX_UPLOAD_BYTES)
    )
    _safe_filename(filename)  # validates; the name itself is recorded at commit time
    incoming = _incoming_dir(request)
    incoming.mkdir(parents=True, exist_ok=True)
    temp_path, bytes_seen, _device_id = await _receive_signed_body(
        request, incoming, max_bytes
    )
    ref = f"{secrets.token_hex(8)}.import"
    try:
        os.replace(temp_path, incoming / ref)
    except OSError as exc:
        _unlink_quietly(temp_path)
        raise HTTPException(
            status_code=500, detail=f"failed to stage audio: {exc}"
        ) from exc
    return {"audio_ref": ref, "bytes_received": bytes_seen}
