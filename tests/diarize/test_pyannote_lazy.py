"""Lazy-import guard: importing the diarizer wrapper must not pull torch/pyannote/soundfile."""

# NB: This is a module-level guard. The end-to-end sidecar cold-start guarantee
# (that creating the FastAPI app doesn't import these libs either) is covered
# separately by tests/api/test_sidecar_cold_start.py (Task 3).

import importlib
import sys


def test_module_import_does_not_load_torch_or_pyannote(monkeypatch):
    forbidden_prefixes = ("torch", "pyannote", "soundfile")
    for mod in list(sys.modules):
        if any(mod == p or mod.startswith(p + ".") for p in forbidden_prefixes):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.delitem(sys.modules, "speechtotext.diarize.pyannote", raising=False)

    importlib.import_module("speechtotext.diarize.pyannote")

    for p in forbidden_prefixes:
        assert p not in sys.modules, (
            f"speechtotext.diarize.pyannote must defer `import {p}` until first diarize call "
            f"so sidecar cold-start stays fast"
        )
