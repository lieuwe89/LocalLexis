from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from speechtotext.api.auth import verify_admin_or_device_or_anonymous
from speechtotext.api.jobs import JobStatus

router = APIRouter()


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def _forward_ask_to_hub(question: str) -> str | None:
    """Joined laptops delegate ask to the hub (full library + LLM live there).
    Returns the hub's job id, or None when this process IS the hub receiving
    its own forward (recursion guard) — caller falls back to the local path."""
    from speechtotext.api import routes_client
    from speechtotext.api.routes_transcripts import _forwarding_in_progress
    from speechtotext.client import identity as _identity
    from speechtotext.client import state as _state
    from speechtotext.client.hub_client import HubClient

    if _forwarding_in_progress.get():
        return None
    st = _state.load()
    ident = _identity.load()
    if st is None or ident is None:
        raise HTTPException(status_code=503, detail="hub state missing")
    hub = HubClient(
        st.hub_url, st.device_id, ident.signing_key(),
        transport=routes_client.sync_test_transport(), timeout=10.0,
    )
    token = _forwarding_in_progress.set(True)
    try:
        return hub.post_json("/library/ask", {"question": question})["job_id"]
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"hub rejected ask: {exc.response.status_code}",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"hub unreachable for ask: {exc}"
        ) from exc
    finally:
        _forwarding_in_progress.reset(token)
        hub.close()


@router.post("/library/ask", status_code=202)
def post_ask(
    body: AskBody,
    request: Request,
    _actor: str = Depends(verify_admin_or_device_or_anonymous),
) -> dict:
    from speechtotext.api import runner  # lazy, matches routes_summarize pattern

    owner = None if _actor in ("admin", "anonymous") else _actor
    runtime = getattr(request.app.state, "hub_runtime", None)
    if runtime is not None and runtime.joined():
        remote_id = _forward_ask_to_hub(body.question)
        if remote_id is not None:
            registry = request.app.state.jobs
            job_id = registry.create(kind="ask", audio_path=None, device_id=owner)
            rec = registry.get(job_id)
            rec.remote_job_id = remote_id
            rec.status = JobStatus.running
            rec.stage = "ask@hub"
            return {"job_id": job_id}
        # else: we ARE the hub receiving our own forward — run locally.

    registry = request.app.state.jobs
    job_id = registry.create(kind="ask", audio_path=None, device_id=owner)
    runner.run_ask_job(registry, job_id, body.question, request.app.state.library_db)
    return {"job_id": job_id}
