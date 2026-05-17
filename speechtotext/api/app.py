from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from speechtotext.api.jobs import JobRegistry
from speechtotext.api.library_db import LibraryDB
from speechtotext.api.routes_config import router as config_router
from speechtotext.api.routes_devices import router as devices_router
from speechtotext.api.routes_jobs import router as jobs_router
from speechtotext.api.routes_models import router as models_router
from speechtotext.api.routes_transcripts import router as transcripts_router
from speechtotext.api.routes_watch import router as watch_router
from speechtotext.api.warmup import warm_microphone_in_background
from speechtotext.api.watcher import WatchController
from speechtotext.config import load_config


def create_app(library_db_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="LocalScribe", version="0.1.0")
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
