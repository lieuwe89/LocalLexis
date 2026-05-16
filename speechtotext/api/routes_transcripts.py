from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from speechtotext.api.library import find_sidecar, scan_dirs
from speechtotext.relabel import relabel

router = APIRouter()


@router.get("/transcripts")
def list_transcripts(request: Request) -> list[dict]:
    return scan_dirs(request.app.state.library_dirs)


@router.get("/transcripts/{tid}")
def get_transcript(tid: str, request: Request) -> dict:
    p = find_sidecar(request.app.state.library_dirs, tid)
    if p is None:
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")
    return json.loads(p.read_text(encoding="utf-8"))


@router.patch("/transcripts/{tid}/relabel")
def patch_relabel(tid: str, mapping: dict[str, str], request: Request) -> dict:
    p = find_sidecar(request.app.state.library_dirs, tid)
    if p is None:
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")
    try:
        relabel(p, mapping)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}
