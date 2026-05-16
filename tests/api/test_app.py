from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


def test_health_endpoint():
    app = create_app()
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_app_exposes_job_registry_via_state():
    app = create_app()
    assert hasattr(app.state, "jobs")
