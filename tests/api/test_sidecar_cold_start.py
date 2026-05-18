"""Boot-time guard: creating the FastAPI app must not import heavy ML libs.

Scope: covers create_app() only. /health, /devices, and /config respond
without touching the ML stack. The runner module (and the audio I/O modules
it imports, e.g. soundfile/sounddevice via speechtotext.ingest.mic) only
loads when a runner-backed endpoint is first invoked — which is acceptable
because those endpoints already imply heavy work.
"""
from __future__ import annotations

import importlib
import sys


def test_create_app_does_not_import_ml_stack(monkeypatch):
    forbidden = ("faster_whisper", "torch", "pyannote", "soundfile")
    for mod in list(sys.modules):
        if any(mod == p or mod.startswith(p + ".") for p in forbidden):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    for mod in list(sys.modules):
        if mod.startswith("speechtotext."):
            monkeypatch.delitem(sys.modules, mod, raising=False)

    app_mod = importlib.import_module("speechtotext.api.app")
    app = app_mod.create_app()
    assert app is not None

    for p in forbidden:
        assert p not in sys.modules, (
            f"create_app() must not transitively import {p}; "
            f"defer it inside the job runner"
        )
