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


def _reset_modules(request, monkeypatch, forbidden: tuple[str, ...]) -> None:
    for mod in list(sys.modules):
        if any(mod == p or mod.startswith(p + ".") for p in forbidden):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    before = {m for m in sys.modules if m.partition(".")[0] == "speechtotext"}
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
            # Re-importing during the test rebinds the child attribute on
            # any SURVIVING parent package (e.g. speechtotext.api on the
            # top-level speechtotext). monkeypatch.delitem only restores
            # the sys.modules key, so without also restoring the attribute
            # the two resolution paths (`import a.b.c as x` walks parent
            # attributes; `from a.b.c import f` uses sys.modules) point at
            # DIFFERENT module objects for the rest of the session — the
            # conftest isolation fixture then patches the wrong one and
            # later tests write to the real app-data dir.
            parent_name, _, child = mod.rpartition(".")
            parent = sys.modules.get(parent_name)
            if parent is not None and hasattr(parent, child):
                monkeypatch.setattr(parent, child, getattr(parent, child))
            monkeypatch.delitem(sys.modules, mod, raising=False)

    def _purge_modules_first_imported_during_test() -> None:
        # Modules that were NOT cached before this test (possible in
        # partial runs, where collection didn't import every test module)
        # are re-imported fresh during the test and would otherwise
        # survive it, mixing module generations for later tests.
        for m in list(sys.modules):
            if m.partition(".")[0] == "speechtotext" and m not in before:
                del sys.modules[m]

    request.addfinalizer(_purge_modules_first_imported_during_test)


def test_create_app_does_not_import_ml_stack(request, monkeypatch, tmp_path):
    _reset_modules(request, monkeypatch, _ML_FORBIDDEN)

    app_mod = importlib.import_module("speechtotext.api.app")
    # Explicit tmp paths: the re-imported modules are fresh objects the
    # autouse app-data isolation fixture never patched, so default paths
    # here would create/open the developer's REAL library.db/devices.db.
    app = app_mod.create_app(
        library_db_path=tmp_path / "library.db",
        devices_db_path=tmp_path / "devices.db",
    )
    assert app is not None

    for p in _ML_FORBIDDEN:
        assert p not in sys.modules, (
            f"create_app() must not transitively import {p}; "
            f"defer it inside the job runner"
        )


def test_runner_import_does_not_load_ml_stack(request, monkeypatch):
    _reset_modules(request, monkeypatch, _RUNNER_FORBIDDEN)

    importlib.import_module("speechtotext.api.runner")

    for p in _RUNNER_FORBIDDEN:
        assert p not in sys.modules, (
            f"importing speechtotext.api.runner must not transitively import {p}; "
            f"the heavy module must only load when a job thread actually runs"
        )
