from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from speechtotext.api.library import find_sidecar
from speechtotext.relabel import relabel

router = APIRouter()


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
