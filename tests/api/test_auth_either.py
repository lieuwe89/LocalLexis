from fastapi import FastAPI, Depends, Request
from fastapi.testclient import TestClient

from speechtotext.api.auth import verify_admin_or_device


def _app_with_dep() -> FastAPI:
    app = FastAPI()

    @app.patch("/thing/{tid}")
    async def patch_thing(tid: str, request: Request, actor: str = Depends(verify_admin_or_device)):
        return {"actor": actor}

    return app


def test_admin_bearer_returns_admin(monkeypatch):
    monkeypatch.setenv("LOCALLEXIS_API_TOKEN", "secret")
    c = TestClient(_app_with_dep())
    r = c.patch("/thing/t1", headers={"Authorization": "Bearer secret"}, json={})
    assert r.status_code == 200
    assert r.json()["actor"] == "admin"


def test_wrong_bearer_without_signature_rejected(monkeypatch):
    monkeypatch.setenv("LOCALLEXIS_API_TOKEN", "secret")
    c = TestClient(_app_with_dep())
    # Wrong bearer -> falls to signature verify -> 401 on missing sig headers.
    r = c.patch("/thing/t1", headers={"Authorization": "Bearer wrong"}, json={})
    assert r.status_code == 401


def test_token_unset_still_requires_signature(monkeypatch):
    monkeypatch.delenv("LOCALLEXIS_API_TOKEN", raising=False)
    c = TestClient(_app_with_dep())
    # No bearer, no signature -> 401 (must NOT fall through to "admin").
    r = c.patch("/thing/t1", json={})
    assert r.status_code == 401
