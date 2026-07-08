from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

router = APIRouter()


class TranscribeRequest(BaseModel):
    path: str
    language: str | None = None
    num_speakers: int | None = None
    backend: str | None = None


@router.post("/jobs/transcribe", status_code=202)
def post_transcribe(req: TranscribeRequest, request: Request) -> dict:
    from speechtotext.api import runner  # lazy: ML stack loads on first job, not at boot
    audio = Path(req.path)
    if not audio.exists() or audio.is_dir():
        raise HTTPException(status_code=404, detail=f"audio not found: {audio}")
    runtime = getattr(request.app.state, "hub_runtime", None)
    if runtime is not None and runtime.joined():
        registry = request.app.state.jobs
        job_id = registry.create(kind="hub_upload", audio_path=str(audio))
        rec = registry.get(job_id)
        rec.stage = "queued-for-hub"
        runtime.enqueue_upload(audio, job_id=job_id)
        runtime.poke()
        return {"job_id": job_id}
    registry = request.app.state.jobs
    job_id = registry.create(kind="transcribe", audio_path=str(audio))
    runner.run_transcribe_job(
        registry, job_id, audio,
        language=req.language,
        num_speakers=req.num_speakers,
        backend=req.backend,
    )
    return {"job_id": job_id}


def _job_dict(rec) -> dict:
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


@router.get("/jobs")
def list_jobs(request: Request, active: bool = False) -> list[dict]:
    from speechtotext.api.jobs import JobStatus
    recs = request.app.state.jobs.all()
    if active:
        recs = [r for r in recs if r.status in (JobStatus.pending, JobStatus.running)]
    return [_job_dict(r) for r in recs]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    try:
        rec = request.app.state.jobs.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    return _job_dict(rec)


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
    from speechtotext.api import runner
    out = Path(req.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    registry = request.app.state.jobs
    job_id = registry.create(kind="record", audio_path=str(out))
    runner.run_record_job(registry, job_id, out, device=req.device)
    return {"job_id": job_id}


@router.post("/jobs/{job_id}/stop")
def stop_job(job_id: str) -> dict:
    from speechtotext.api import runner
    ok = runner.stop_record_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not recording or already stopped")
    return {"ok": True}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    from speechtotext.api import runner
    ok = runner.cancel_transcribe_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not active or already finished")
    return {"ok": True}
