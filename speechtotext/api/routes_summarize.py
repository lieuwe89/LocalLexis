from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from speechtotext.api.library import find_sidecar
from speechtotext.api.routes_transcripts import _get_transcript_lock
from speechtotext.config import DEFAULT_CONFIG_PATH, load_config
from speechtotext.summarize.provider import ProviderError, provider_from_config

router = APIRouter()


@router.post("/transcripts/{tid}/summarize", status_code=202)
def post_summarize(tid: str, request: Request) -> dict:
    from speechtotext.api import runner  # lazy, matches routes_jobs pattern

    db = request.app.state.library_db
    p = db.get_path(tid) or find_sidecar(set(request.app.state.library_dirs), tid)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")
    registry = request.app.state.jobs
    job_id = registry.create(kind="summarize", audio_path=None)
    lock = _get_transcript_lock(request.app.state, tid)
    runner.run_summarize_job(
        registry, job_id, p, lock, on_written=db.upsert_path
    )
    return {"job_id": job_id}


@router.get("/summarize/models")
def summarize_models() -> dict:
    cfg = load_config(config_path=DEFAULT_CONFIG_PATH)
    try:
        models = provider_from_config(cfg.summarize).list_models()
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"models": models}
