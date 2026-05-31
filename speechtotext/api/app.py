from __future__ import annotations

import hmac
import os
import re
import threading
import weakref
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from speechtotext import __version__
from speechtotext.api.auth import NonceCache
from speechtotext.api.devices import DeviceRegistry
from speechtotext.api.jobs import JobRegistry
from speechtotext.api.library_db import LibraryDB
from speechtotext.api.pairing import PairingTokenStore
from speechtotext.api.reconcile import LibraryReconciler
from speechtotext.api.routes_config import router as config_router
from speechtotext.api.routes_devices import router as devices_router
from speechtotext.api.routes_hub import router as hub_router
from speechtotext.api.routes_ingest import (
    DEFAULT_MAX_UPLOAD_BYTES,
    router as ingest_router,
    sweep_partial_uploads,
)
from speechtotext.api.routes_jobs import router as jobs_router
from speechtotext.api.routes_models import router as models_router
from speechtotext.api.routes_pairing import router as pairing_router
from speechtotext.api.routes_sync import router as sync_router
from speechtotext.api.routes_transcripts import router as transcripts_router
from speechtotext.api.routes_watch import router as watch_router
from speechtotext.api.warmup import warm_microphone_in_background
from speechtotext.api.watcher import WatchController
from speechtotext.config import load_config


# Routes that authenticate via the LAN-device flow rather than the
# Tauri-launcher bearer token. BearerAuthMiddleware lets these through
# so paired phones / tablets (which never see LOCALLEXIS_API_TOKEN) can
# reach the multi-device sync surface. The route handlers themselves
# enforce auth: ``POST /pair`` validates the single-use token in the
# body; ``/sync/*`` and ``PATCH /transcripts/{tid}`` validate an
# Ed25519 signature via :func:`speechtotext.api.auth.verify_device_signature`.
#
# Anything not matched here stays bearer-gated, so admin endpoints
# (/pair/tokens, /config, /jobs, PATCH /transcripts/{tid}/relabel,
# GET /transcripts, etc.) cannot be reached from the LAN.
_SIGNED_TRANSCRIPT_PATCH = re.compile(r"^/transcripts/[^/]+$")


def _is_lan_signed_route(path: str, method: str) -> bool:
    if path == "/pair" and method == "POST":
        return True
    if method == "GET" and (
        path == "/sync/snapshot" or path.startswith("/sync/since/")
    ):
        return True
    if method == "PATCH" and _SIGNED_TRANSCRIPT_PATCH.fullmatch(path):
        return True
    if path == "/jobs/upload" and method == "POST":
        return True
    return False


class BearerAuthMiddleware:
    """Reject requests without a matching bearer token when one is required.

    The Tauri launcher sets LOCALLEXIS_API_TOKEN before spawning the sidecar
    so the desktop process is the only client that knows the token. When the
    env var is unset (e.g. running `stt serve` from the CLI) we skip auth so
    standalone use is still possible. Preflight (OPTIONS) is always passed
    through so CORS can answer with the right headers.

    LAN-device routes (see :func:`_is_lan_signed_route`) bypass the bearer
    check because they authenticate via signed requests instead. The route's
    own dep rejects anything missing or forged.

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
        method = scope.get("method", "")
        path = scope.get("path", "")
        if not expected or method == "OPTIONS":
            await self.app(scope, receive, send)
            return
        if _is_lan_signed_route(path, method):
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


@asynccontextmanager
async def _lifespan(app: FastAPI):
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
    # Streaming /jobs/upload writes a <random>.partial scratch file
    # while it hashes; a crash mid-stream would leak it indefinitely.
    removed = sweep_partial_uploads(Path(app.state.incoming_dir))
    if removed:
        import logging

        logging.getLogger("speechtotext.api").info(
            "swept %d orphan partial upload(s) at startup", removed
        )
    yield


def create_app(
    library_db_path: Path | None = None,
    devices_db_path: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="LocalLexis", version=__version__, lifespan=_lifespan)
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
    # Gates the library walk behind a per-dir mtime check so list/sync
    # requests don't stat every transcript file when nothing changed.
    app.state.library_reconciler = LibraryReconciler(app.state.library_db)
    app.state.pairing_tokens = PairingTokenStore()
    app.state.device_registry = DeviceRegistry(devices_db_path)
    # Replay defense for device-signed requests (see auth.verify_device_signature).
    app.state.nonce_cache = NonceCache()
    # Per-transcript write lock for PATCH /transcripts/{tid}. Two paired
    # devices PATCHing the same transcript would otherwise race on the
    # read-merge-write sequence and one would clobber the other. Held in a
    # weak-value map so a transcript's lock is GC'd once no request holds
    # it — otherwise the dict grows one entry per transcript-id forever.
    app.state.transcript_locks: weakref.WeakValueDictionary[str, threading.Lock] = (
        weakref.WeakValueDictionary()
    )
    app.state.transcript_locks_dict_lock = threading.Lock()
    app.state.max_upload_bytes = DEFAULT_MAX_UPLOAD_BYTES

    config_default_out_dir: Path | None = None
    try:
        _cfg = load_config()
        if _cfg.default_out_dir:
            config_default_out_dir = _cfg.default_out_dir
            app.state.library_dirs.add(config_default_out_dir)
    except Exception:
        pass
    if config_default_out_dir:
        app.state.incoming_dir = config_default_out_dir / "incoming"
    else:
        from speechtotext.api import library_db as library_db_module

        app.state.incoming_dir = library_db_module.default_app_data_dir() / "incoming"

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
    app.include_router(hub_router)
    app.include_router(config_router)
    app.include_router(ingest_router)
    app.include_router(jobs_router)
    app.include_router(models_router)
    app.include_router(pairing_router)
    app.include_router(sync_router)
    app.include_router(transcripts_router)
    app.include_router(watch_router)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    return app
