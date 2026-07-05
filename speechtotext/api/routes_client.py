"""Loopback endpoints for the desktop UI to manage hub-client mode.

These are hub-*client* controls (join/leave/status), distinct from the
hub-*server* routes (pairing mint, sync). They stay bearer-gated by the
existing middleware (not in the LAN-signed route set).

``_TEST_TRANSPORT`` lets tests route the outbound pairing/upload HTTP
into an in-process ASGI app; production leaves it None.
"""

from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from speechtotext.client import join as join_module

router = APIRouter()

# In tests this is set to an ``httpx.ASGITransport`` so outbound pairing /
# upload / sync HTTP is routed into the in-process app instead of the LAN.
# Production leaves it None.
_TEST_TRANSPORT: httpx.BaseTransport | None = None


class _SyncASGITransport(httpx.BaseTransport):
    """Adapt an async ``ASGITransport`` for use by a synchronous
    ``httpx.Client``.

    ``join_hub`` and ``HubClient`` both talk over sync clients, but modern
    httpx ships ``ASGITransport`` as async-only. This drives each request
    through a throwaway event loop so loopback tests (client == hub) work
    without an async client. Only used when a test transport is installed.
    """

    def __init__(self, transport: httpx.ASGITransport) -> None:
        self._async = transport

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        content = request.read()

        async def _go() -> httpx.Response:
            areq = httpx.Request(
                request.method,
                request.url,
                headers=request.headers,
                content=content,
            )
            resp = await self._async.handle_async_request(areq)
            body = await resp.aread()
            await resp.aclose()
            return httpx.Response(
                resp.status_code,
                headers=resp.headers,
                content=body,
                request=request,
            )

        return asyncio.run(_go())


def sync_test_transport() -> httpx.BaseTransport | None:
    """The installed test transport, made safe for synchronous clients.

    Returns None in production (no test transport). An ``ASGITransport`` is
    wrapped; any already-sync transport is passed through unchanged.
    """
    t = _TEST_TRANSPORT
    if t is None:
        return None
    if isinstance(t, httpx.ASGITransport):
        return _SyncASGITransport(t)
    return t


class JoinRequest(BaseModel):
    pairing_string: str = Field(min_length=1)
    device_name: str = Field(min_length=1, max_length=128)


def _runtime(request: Request):
    return request.app.state.hub_runtime


@router.get("/client/hub")
def hub_status(request: Request) -> dict:
    status = _runtime(request).status()
    if not status["joined"]:
        return {"joined": False}
    return status


@router.post("/client/hub/join")
def hub_join(req: JoinRequest, request: Request) -> dict:
    runtime = _runtime(request)
    if runtime.joined():
        raise HTTPException(status_code=409, detail="already joined a hub")
    try:
        st = join_module.join_hub(
            req.pairing_string,
            device_name=req.device_name,
            transport=sync_test_transport(),
        )
    except join_module.PairingStringError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"hub rejected pairing: {exc.response.status_code}",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"cannot reach hub: {exc}")
    runtime.start()
    return {"joined": True, "device_id": st.device_id,
            "hub_url": st.hub_url, "workspace_id": st.workspace_id}


@router.post("/client/hub/leave")
def hub_leave(request: Request) -> dict:
    runtime = _runtime(request)
    runtime.stop()
    join_module.leave_hub()
    return {"joined": False}
