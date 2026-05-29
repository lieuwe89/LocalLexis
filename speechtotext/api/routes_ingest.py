"""Audio ingest endpoints for paired LAN devices.

The first recorder slice accepts a complete audio file as one signed request.
Chunked ingest can be layered beside this once the ESP32 signing path is proven.
"""

from __future__ import annotations

import os
import re
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from speechtotext.api import library_db as library_db_module
from speechtotext.api.auth import verify_device_signature

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


async def verify_upload_signature(request: Request) -> str:
    max_bytes = int(
        getattr(request.app.state, "max_upload_bytes", DEFAULT_MAX_UPLOAD_BYTES)
    )
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
    return await verify_device_signature(request)


def _unique_upload_path(root: Path, filename: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    suffix = secrets.token_hex(4)
    return root / f"{stamp}-{suffix}-{filename}"


def _write_atomic(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(body)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise HTTPException(
            status_code=500, detail=f"failed to store upload: {exc}"
        ) from exc


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


@router.post("/jobs/upload", status_code=202, response_model=UploadResponse)
async def post_upload(
    request: Request,
    filename: str | None = Query(default=None, max_length=180),
    _device_id: str = Depends(verify_upload_signature),
) -> UploadResponse:
    """Accept a complete signed audio file and dispatch transcription."""
    body = await request.body()
    if not body:
        raise HTTPException(
            status_code=400, detail="audio upload body cannot be empty"
        )

    incoming = _incoming_dir(request)
    audio_path = _unique_upload_path(incoming, _safe_filename(filename))
    _write_atomic(audio_path, body)

    registry = request.app.state.jobs
    job_id = registry.create(kind="transcribe", audio_path=str(audio_path))

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

    return UploadResponse(
        job_id=job_id,
        bytes_received=len(body),
    )
