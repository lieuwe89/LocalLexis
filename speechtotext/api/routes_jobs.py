from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from speechtotext.api.auth import verify_admin_or_device_or_anonymous
from speechtotext.api.jobs import JobStatus

router = APIRouter()


class TranscribeRequest(BaseModel):
    path: str
    language: str | None = None
    num_speakers: int | None = None
    backend: str | None = None


def _route_capture_to_hub(runtime) -> bool:
    """Joined captures go to the hub unless the user chose local-when-offline
    and the hub is currently unreachable. Short probe timeout: this runs in
    the capture request path, and the slow case (hub down) is exactly when
    the user is waiting to fall back to local."""
    # ponytail: no probe cache — N files dropped while offline probe
    # serially (~1s each); cache the result briefly if watch storms bite.
    from speechtotext.client import state as state_module

    st = state_module.load()
    mode = getattr(st, "offline_capture", "local") if st else "local"
    if mode == "queue":
        return True
    return runtime.hub_reachable(timeout=1.0)


@router.post("/jobs/transcribe", status_code=202)
def post_transcribe(req: TranscribeRequest, request: Request) -> dict:
    from speechtotext.api import runner  # lazy: ML stack loads on first job, not at boot
    audio = Path(req.path)
    if not audio.exists() or audio.is_dir():
        raise HTTPException(status_code=404, detail=f"audio not found: {audio}")
    runtime = getattr(request.app.state, "hub_runtime", None)
    if runtime is not None and runtime.joined() and _route_capture_to_hub(runtime):
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
        "result": rec.result,
    }


@router.get("/jobs")
def list_jobs(request: Request, active: bool = False) -> list[dict]:
    recs = request.app.state.jobs.all()
    if active:
        recs = [r for r in recs if r.status in (JobStatus.pending, JobStatus.running)]
    return [_job_dict(r) for r in recs]


def _fetch_remote_job(remote_id: str) -> dict:
    """GET a proxied ask job's status+result from the hub.

    Builds the signed client the same way ``routes_ask._forward_ask_to_hub``
    does. No recursion guard is needed here (unlike the POST forward): a
    self-joined loopback would hit the hub's own ``get_job``, but that
    record's ``remote_job_id`` is always None (only the client-side record
    created after a successful forward carries one), so the hub-side call
    can never re-enter this proxy branch.
    """
    from speechtotext.api import routes_client
    from speechtotext.client import identity as _identity
    from speechtotext.client import state as _state
    from speechtotext.client.hub_client import HubClient

    st = _state.load()
    ident = _identity.load()
    if st is None or ident is None:
        raise RuntimeError("hub state missing")
    hub = HubClient(
        st.hub_url, st.device_id, ident.signing_key(),
        transport=routes_client.sync_test_transport(), timeout=10.0,
    )
    try:
        return hub.get_json(f"/jobs/{remote_id}")
    finally:
        hub.close()


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    request: Request,
    _actor: str = Depends(verify_admin_or_device_or_anonymous),
) -> dict:
    try:
        rec = request.app.state.jobs.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")

    # Proxied ask jobs (remote_job_id set): fields are mutated without a
    # lock — concurrent polls may race, but each write is a full overwrite
    # from the hub's latest state, so it self-heals on the next poll. Note
    # SSE /jobs/{id}/stream is NOT proxied for these jobs: no events are
    # ever published locally, so a subscriber would hang — polling only.
    if rec.remote_job_id and rec.status not in (JobStatus.complete, JobStatus.failed):
        try:
            remote = _fetch_remote_job(rec.remote_job_id)
        except Exception as exc:
            rec.status = JobStatus.failed
            rec.error = f"hub unreachable while polling ask job: {exc}"
            return _job_dict(rec)
        rec.stage = remote.get("stage") or rec.stage
        rec.percent = float(remote.get("percent") or rec.percent)
        rec.error = remote.get("error")
        rec.result = remote.get("result")
        if remote.get("status") == "complete":
            rec.status = JobStatus.complete
        elif remote.get("status") == "failed":
            rec.status = JobStatus.failed
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
