from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


def test_list_jobs_empty(client):
    assert client.get("/jobs").json() == []


def test_list_jobs_active_filter(client, app):
    reg = app.state.jobs
    j1 = reg.create(kind="transcribe", audio_path="/tmp/a.wav")
    j2 = reg.create(kind="transcribe", audio_path="/tmp/b.wav")
    from speechtotext.api.jobs import JobStatus
    reg.get(j2).status = JobStatus.complete

    all_jobs = client.get("/jobs").json()
    assert {j["id"] for j in all_jobs} == {j1, j2}

    active = client.get("/jobs", params={"active": "true"}).json()
    assert [j["id"] for j in active] == [j1]
    assert active[0]["kind"] == "transcribe"
    assert active[0]["status"] == "pending"
