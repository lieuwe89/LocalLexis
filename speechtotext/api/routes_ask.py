from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter()


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@router.post("/library/ask", status_code=202)
def post_ask(body: AskBody, request: Request) -> dict:
    from speechtotext.api import runner  # lazy, matches routes_summarize pattern

    registry = request.app.state.jobs
    job_id = registry.create(kind="ask", audio_path=None)
    runner.run_ask_job(registry, job_id, body.question, request.app.state.library_db)
    return {"job_id": job_id}
