"""Commit step of the transcript import: pair a staged audio ref with a
complete transcript doc, write the sidecar files, index them.

The doc is stored as-is (no pydantic re-serialization) so unknown/future
fields — _clocks, _history, summary — survive the trip untouched.
"""
from __future__ import annotations

import os
import re
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from speechtotext.api.auth import verify_admin_or_device
from speechtotext.api.routes_ingest import (
    DEFAULT_MAX_UPLOAD_BYTES,
    _incoming_dir,
    _safe_filename,
)
from speechtotext.api.routes_transcripts import (
    _atomic_write_json,
    _get_transcript_lock,
    _rewrite_txt_sidecar,
)

router = APIRouter()

_TID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


class ImportBody(BaseModel):
    tid: str = Field(min_length=1, max_length=255)
    transcript: dict
    audio_ref: str | None = None
    audio_filename: str | None = None

    model_config = {"extra": "forbid"}


def _check_content_length(request: Request) -> None:
    raw = request.headers.get("content-length")
    if raw is None:
        raise HTTPException(status_code=411, detail="Content-Length required")
    try:
        length = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="invalid Content-Length"
        ) from exc
    max_bytes = int(
        getattr(request.app.state, "max_upload_bytes", DEFAULT_MAX_UPLOAD_BYTES)
    )
    if length > max_bytes:
        raise HTTPException(
            status_code=413, detail=f"import exceeds {max_bytes} byte limit"
        )


def _check_shape(doc: dict) -> None:
    segments = doc.get("segments")
    if segments is not None and (
        not isinstance(segments, list)
        or not all(isinstance(s, dict) for s in segments)
    ):
        raise HTTPException(status_code=400, detail="invalid transcript shape")
    speakers = doc.get("speakers")
    if speakers is not None and not isinstance(speakers, dict):
        raise HTTPException(status_code=400, detail="invalid transcript shape")


@router.post("/transcripts/import")
def post_import(
    body: ImportBody,
    request: Request,
    device_id: str = Depends(verify_admin_or_device),
) -> dict:
    _check_content_length(request)
    if not _TID_RE.fullmatch(body.tid):
        raise HTTPException(status_code=400, detail="invalid transcript id")
    _check_shape(body.transcript)

    db = request.app.state.library_db
    incoming = _incoming_dir(request)
    json_path = incoming / f"{body.tid}.json"

    lock = _get_transcript_lock(request.app.state, body.tid)
    with lock:
        # A DB miss isn't proof of absence: an on-disk json may be unindexed
        # after a restart or mid-rebuild, so check the file too.
        if db.get_path(body.tid) is not None or json_path.exists():
            return {"imported": False, "reason": "exists"}

        incoming.mkdir(parents=True, exist_ok=True)
        doc = dict(body.transcript)
        # audio_path is always hub-controlled: /transcripts/{tid}/audio serves
        # it verbatim, so a client-supplied path would disclose arbitrary
        # hub-readable files. Without staged audio there is no hub audio.
        doc.pop("audio_path", None)

        if body.audio_ref is not None:
            if (
                "/" in body.audio_ref
                or "\\" in body.audio_ref
                or not body.audio_ref.endswith(".import")
            ):
                raise HTTPException(status_code=400, detail="invalid audio_ref")
            staged = incoming / body.audio_ref
            if not staged.is_file():
                raise HTTPException(
                    status_code=400, detail="audio_ref not found (stage it first)"
                )
            audio_name = _safe_filename(body.audio_filename)
            stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
            final_audio = incoming / f"{stamp}-{secrets.token_hex(4)}-{audio_name}"
            os.replace(staged, final_audio)
            doc["audio_path"] = str(final_audio)

        _atomic_write_json(json_path, doc)
        _rewrite_txt_sidecar(json_path, doc)
        db.upsert_path(json_path)
    return {"imported": True}
