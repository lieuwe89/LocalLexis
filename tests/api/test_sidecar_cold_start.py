"""Boot-time guard: creating the FastAPI app AND importing the job runner
must not import heavy ML libs (or, for the runner, audio I/O either).

Scope: covers both create_app() and `import speechtotext.api.runner`.
/health and /config respond without touching the ML stack. The /devices
route legitimately reaches for sounddevice (to enumerate inputs), so the
create_app() check does not forbid it — but importing the job runner
itself stays free of faster_whisper, torch, pyannote, soundfile, AND
sounddevice. Those only load when a job thread actually runs (acceptable
because that endpoint already implies heavy work).
"""
from __future__ import annotations

import importlib
import sys


_ML_FORBIDDEN = ("faster_whisper", "torch", "pyannote", "soundfile")
_RUNNER_FORBIDDEN = _ML_FORBIDDEN + ("sounddevice",)


def _reset_modules(monkeypatch, forbidden: tuple[str, ...]) -> None:
    for mod in list(sys.modules):
        if any(mod == p or mod.startswith(p + ".") for p in forbidden):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    for mod in list(sys.modules):
        # Leave speechtotext.client.* cached: create_app() legitimately
        # imports it, and re-importing would rebind its paths module to a
        # fresh object that the autouse app-data isolation fixture (which
        # patched the *original* module) no longer covers — leaking client
        # writes to the real home dir for the rest of the session. The
        # client package holds no ML imports, so keeping it cached does not
        # weaken the ML-boot guard.
        if mod.startswith("speechtotext.") and not mod.startswith(
            "speechtotext.client"
        ):
            monkeypatch.delitem(sys.modules, mod, raising=False)


def test_create_app_does_not_import_ml_stack(monkeypatch):
    _reset_modules(monkeypatch, _ML_FORBIDDEN)

    app_mod = importlib.import_module("speechtotext.api.app")
    app = app_mod.create_app()
    assert app is not None

    for p in _ML_FORBIDDEN:
        assert p not in sys.modules, (
            f"create_app() must not transitively import {p}; "
            f"defer it inside the job runner"
        )


def test_runner_import_does_not_load_ml_stack(monkeypatch):
    _reset_modules(monkeypatch, _RUNNER_FORBIDDEN)

    importlib.import_module("speechtotext.api.runner")

    for p in _RUNNER_FORBIDDEN:
        assert p not in sys.modules, (
            f"importing speechtotext.api.runner must not transitively import {p}; "
            f"the heavy module must only load when a job thread actually runs"
        )
