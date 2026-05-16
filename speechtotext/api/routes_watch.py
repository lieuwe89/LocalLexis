from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from speechtotext.api import runner
from speechtotext.config import load_config

router = APIRouter()


class WatchStartRequest(BaseModel):
    directory: str
    recursive: bool = False


@router.post("/watch/start")
def start(req: WatchStartRequest, request: Request) -> dict:
    d = Path(req.directory)
    if not d.is_dir():
        raise HTTPException(status_code=400, detail=f"not a directory: {d}")
    cfg = load_config()
    registry = request.app.state.jobs
    ctrl = request.app.state.watcher

    def _on_file(path: Path):
        job_id = registry.create(kind="transcribe", audio_path=str(path))
        runner.run_transcribe_job(registry, job_id, path)

    try:
        ctrl.start(
            directory=d,
            extensions=list(cfg.watch.extensions),
            debounce_seconds=cfg.watch.debounce_seconds,
            recursive=req.recursive,
            on_file=_on_file,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return ctrl.status()


@router.post("/watch/stop")
def stop(request: Request) -> dict:
    request.app.state.watcher.stop()
    return request.app.state.watcher.status()


@router.get("/watch/status")
def status(request: Request) -> dict:
    return request.app.state.watcher.status()
