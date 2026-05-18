"""Lazy-import guard: importing the wrapper must not import faster_whisper."""
# NB: This is a module-level guard. The end-to-end sidecar cold-start guarantee
# (that creating the FastAPI app doesn't import faster_whisper either) is
# covered separately by tests/api/test_sidecar_cold_start.py (Task 3).

import importlib
import sys


def test_module_import_does_not_load_faster_whisper(monkeypatch):
    for mod in list(sys.modules):
        if mod == "faster_whisper" or mod.startswith("faster_whisper."):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.delitem(sys.modules, "speechtotext.asr.faster_whisper", raising=False)

    importlib.import_module("speechtotext.asr.faster_whisper")

    assert "faster_whisper" not in sys.modules, (
        "speechtotext.asr.faster_whisper must defer `from faster_whisper import WhisperModel` "
        "until first use so sidecar cold-start stays fast"
    )
