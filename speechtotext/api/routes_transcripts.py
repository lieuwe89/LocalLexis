from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from speechtotext.api.auth import verify_device_signature
from speechtotext.api.crdt import (
    OpRequest,
    TranscriptState,
    merge_op,
)
from speechtotext.api.library import find_sidecar
from speechtotext.api.workspace import (
    bump_lamport_to,
    get_lamport,
    get_workspace_id,
)
from speechtotext.relabel import relabel

router = APIRouter()


class PatchOpBody(BaseModel):
    """Incoming CRDT op for ``PATCH /transcripts/{tid}``.

    The hub assigns the authoritative ``lamport`` on apply and stamps
    the verified ``device_id`` from the signed request — clients cannot
    supply a device attribution. Clients pass the highest lamport they
    have observed so far so the hub can avoid demoting them.
    """

    op: str = Field(description="Op type. v1 supports 'relabel'.")
    key: str = Field(description="Dotted key, e.g. 'speakers.SPEAKER_00'.")
    value: Any = Field(description="New value at the key.")
    lamport_observed: int = Field(
        ge=0,
        description="Highest Lamport the client has seen for this workspace.",
    )

    model_config = {"extra": "ignore"}


class PatchResult(BaseModel):
    """Result of a successful PATCH op.

    ``applied`` is the canonical op record (with hub-assigned Lamport
    and timestamp). ``speakers`` / ``_clocks`` / ``_history`` mirror
    the on-disk transcript's new state. ``lamport_assigned`` lets the
    client advance its observed counter.
    """

    applied: dict
    speakers: dict
    clocks: dict = Field(alias="_clocks")
    history: list[dict] = Field(alias="_history")
    lamport_assigned: int

    model_config = {"populate_by_name": True}


def _atomic_write_json(path: Path, doc: dict) -> None:
    """Same atomic-tmp-then-rename pattern as ``writer._atomic_write``."""
    content = json.dumps(doc, indent=2, ensure_ascii=False)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


@router.get("/transcripts")
def list_transcripts(
    request: Request,
    q: str | None = Query(default=None, description="full-text search query"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict]:
    db = request.app.state.library_db
    # Cheap drift check before responding so the user sees rows that match
    # what's actually on disk right now.
    db.sync_dirs(list(request.app.state.library_dirs))
    if q:
        return db.search(q, limit=limit)
    return db.list(limit=limit)


@router.get("/transcripts/{tid}")
def get_transcript(tid: str, request: Request) -> dict:
    db = request.app.state.library_db
    p = db.get_path(tid) or find_sidecar(request.app.state.library_dirs, tid)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")
    doc = json.loads(p.read_text(encoding="utf-8"))
    txt = p.with_suffix(".txt")
    doc["paths"] = {
        "json": str(p),
        **({"txt": str(txt)} if txt.is_file() else {}),
    }
    return doc


@router.patch("/transcripts/{tid}/relabel")
def patch_relabel(tid: str, mapping: dict[str, str], request: Request) -> dict:
    db = request.app.state.library_db
    p = db.get_path(tid) or find_sidecar(request.app.state.library_dirs, tid)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")
    try:
        relabel(p, mapping)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # speaker_labels participate in FTS, so reindex this row after relabel
    db.upsert_path(p)
    return {"ok": True}


@router.patch("/transcripts/{tid}", response_model=PatchResult)
def patch_transcript_op(
    tid: str,
    body: PatchOpBody,
    request: Request,
    device_id: str = Depends(verify_device_signature),
) -> PatchResult:
    """Apply a CRDT op to a transcript.

    Unlike ``/transcripts/{tid}/relabel`` (which takes a bulk mapping
    and applies it locally with no clock awareness), this endpoint is
    the canonical entry point for device-driven edits that participate
    in multi-device sync. The hub assigns the Lamport, runs LWW per
    key, and records the op in the transcript's ``_history``.
    """
    db = request.app.state.library_db
    p = db.get_path(tid) or find_sidecar(request.app.state.library_dirs, tid)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500, detail=f"failed to read transcript: {exc}"
        )

    state = TranscriptState.from_json(doc)
    op_request = OpRequest(
        op=body.op,
        key=body.key,
        value=body.value,
        device=device_id,
        lamport_observed=body.lamport_observed,
    )
    try:
        new_state, new_lamport, applied_op = merge_op(
            state, op_request, get_lamport()
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Persist new counter before writing the file so a crash between
    # write and counter-update is recoverable from the transcript log.
    bump_lamport_to(new_lamport)

    # Merge CRDT state back into the full doc and write atomically.
    # Stamp workspace_id if the transcript pre-dates the v2 schema.
    if not doc.get("_workspace_id"):
        doc["_workspace_id"] = get_workspace_id()
    doc["speakers"] = dict(new_state.speakers)
    doc["_clocks"] = {k: asdict(c) for k, c in new_state.clocks.items()}
    doc["_history"] = [asdict(op) for op in new_state.history]
    _atomic_write_json(p, doc)

    # speaker_labels participate in FTS, so reindex.
    db.upsert_path(p)

    return PatchResult(
        applied=asdict(applied_op),
        speakers=dict(new_state.speakers),
        _clocks={k: asdict(c) for k, c in new_state.clocks.items()},
        _history=[asdict(op) for op in new_state.history],
        lamport_assigned=new_lamport,
    )
