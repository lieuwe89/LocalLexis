from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from speechtotext.api import trash
from speechtotext.api.routes_transcripts import _get_transcript_lock

router = APIRouter()


@router.get("/trash")
def list_trash(request: Request) -> list[dict]:
    return trash.list_trash(set(request.app.state.library_dirs))


@router.post("/trash/{tid}/restore")
def restore_item(tid: str, request: Request) -> dict:
    lock = _get_transcript_lock(request.app.state, tid)
    with lock:
        try:
            json_path = trash.restore(set(request.app.state.library_dirs), tid)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"not in trash: {tid}")
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        request.app.state.library_db.upsert_path(json_path)
    return {"ok": True, "restored": str(json_path)}


@router.delete("/trash/{tid}")
def purge_item(tid: str, request: Request) -> dict:
    lock = _get_transcript_lock(request.app.state, tid)
    with lock:
        n = trash.purge(set(request.app.state.library_dirs), tid)
        if n == 0:
            raise HTTPException(status_code=404, detail=f"not in trash: {tid}")
    return {"ok": True, "purged": n}


@router.delete("/trash")
def empty_trash(request: Request) -> dict:
    return {"ok": True, "purged": trash.purge(set(request.app.state.library_dirs))}
