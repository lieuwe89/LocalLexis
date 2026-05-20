from __future__ import annotations

import hmac
import os
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from speechtotext import __version__
from speechtotext.api.jobs import JobRegistry
from speechtotext.api.library_db import LibraryDB
from speechtotext.api.pairing import PairingTokenStore
from speechtotext.api.routes_config import router as config_router
from speechtotext.api.routes_devices import router as devices_router
from speechtotext.api.routes_jobs import router as jobs_router
from speechtotext.api.routes_models import router as models_router
from speechtotext.api.routes_pairing import router as pairing_router
from speechtotext.api.routes_transcripts import router as transcripts_router
from speechtotext.api.routes_watch import router as watch_router
from speechtotext.api.warmup import warm_microphone_in_background
from speechtotext.api.watcher import WatchController
from speechtotext.config import load_config


class BearerAuthMiddleware:
    """Reject requests without a matching bearer token when one is required.

    The Tauri launcher sets LOCALLEXIS_API_TOKEN before spawning the sidecar
    so the desktop process is the only client that knows the token. When the
    env var is unset (e.g. running `stt serve` from the CLI) we skip auth so
    standalone use is still possible. Preflight (OPTIONS) is always passed
    through so CORS can answer with the right headers.

    Implemented as raw ASGI middleware (not BaseHTTPMiddleware) to avoid
    buffering streaming responses such as SSE.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        expected = os.environ.get("LOCALLEXIS_API_TOKEN")
        if not expected or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        auth = ""
        for name, value in scope.get("headers") or []:
            if name == b"authorization":
                auth = value.decode("latin-1", errors="replace")
                break
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
            response = JSONResponse({"detail": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(library_db_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="LocalLexis", version=__version__)
    # Order matters: middleware added LAST runs OUTERMOST, so CORS must be
    # added after auth — that way 401 responses still carry CORS headers and
    # the browser surfaces them as auth errors rather than CORS errors.
    app.add_middleware(BearerAuthMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(tauri://.*|https?://(localhost|127\.0\.0\.1)(:\d+)?)$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.jobs = JobRegistry()
    app.state.watcher = WatchController()
    app.state.library_dirs: set[Path] = set()
    app.state.library_db = LibraryDB(library_db_path)
    app.state.pairing_tokens = PairingTokenStore()

    try:
        _cfg = load_config()
        if _cfg.default_out_dir:
            app.state.library_dirs.add(_cfg.default_out_dir)
    except Exception:
        pass

    def _on_complete_dir(dir_path: Path) -> None:
        app.state.library_dirs.add(dir_path)
        # Re-sync just this directory so the new transcript is searchable
        # the moment the job finishes. Cheap because mtime checks short-
        # circuit unchanged rows.
        threading.Thread(
            target=app.state.library_db.sync_dirs,
            args=([dir_path],),
            daemon=True,
        ).start()

    app.state.jobs.set_on_complete_dir(_on_complete_dir)

    app.include_router(devices_router)
    app.include_router(config_router)
    app.include_router(jobs_router)
    app.include_router(models_router)
    app.include_router(pairing_router)
    app.include_router(transcripts_router)
    app.include_router(watch_router)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.on_event("startup")
    def _on_startup() -> None:
        # Trigger the macOS mic permission prompt at app launch instead of
        # when the user clicks Record, so the first recording isn't missing
        # its opening seconds while the user is dismissing a dialog.
        warm_microphone_in_background()
        # Reconcile the library index with what is actually on disk. Runs
        # in a background thread so a large library does not delay /health.
        threading.Thread(
            target=app.state.library_db.sync_dirs,
            args=(list(app.state.library_dirs),),
            daemon=True,
        ).start()

    return app
