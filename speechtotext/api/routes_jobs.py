from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from speechtotext.api import runner

router = APIRouter()


class TranscribeRequest(BaseModel):
    path: str
    language: str | None = None
    num_speakers: int | None = None
    backend: str | None = None


@router.post("/jobs/transcribe", status_code=202)
def post_transcribe(req: TranscribeRequest, request: Request) -> dict:
    audio = Path(req.path)
    if not audio.exists() or audio.is_dir():
        raise HTTPException(status_code=404, detail=f"audio not found: {audio}")
    registry = request.app.state.jobs
    job_id = registry.create(kind="transcribe", audio_path=str(audio))
    runner.run_transcribe_job(
        registry, job_id, audio,
        language=req.language,
        num_speakers=req.num_speakers,
        backend=req.backend,
    )
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    try:
        rec = request.app.state.jobs.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    return {
        "id": rec.id,
        "kind": rec.kind,
        "status": rec.status.value,
        "stage": rec.stage,
        "percent": rec.percent,
        "error": rec.error,
        "transcript_id": rec.transcript_id,
        "audio_path": rec.audio_path,
        "paths": rec.paths,
    }


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str, request: Request):
    registry = request.app.state.jobs
    try:
        registry.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")

    async def event_gen():
        async for ev in registry.subscribe(job_id):
            yield {"event": "message", "data": _json_dumps(asdict(ev))}

    return EventSourceResponse(event_gen())


def _json_dumps(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


class RecordRequest(BaseModel):
    out: str
    device: str | None = None


@router.post("/jobs/record", status_code=202)
def post_record(req: RecordRequest, request: Request) -> dict:
    out = Path(req.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    registry = request.app.state.jobs
    job_id = registry.create(kind="record", audio_path=str(out))
    runner.run_record_job(registry, job_id, out, device=req.device)
    return {"job_id": job_id}


@router.post("/jobs/{job_id}/stop")
def stop_job(job_id: str) -> dict:
    ok = runner.stop_record_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not recording or already stopped")
    return {"ok": True}
