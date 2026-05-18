"""Lazy-import guard: importing the mic module must not import sounddevice or soundfile."""
# NB: This is a module-level guard. The broader sidecar cold-start guarantee
# (that create_app() AND importing the job runner stay free of these heavy
# audio I/O libs too) is covered separately by tests/api/test_sidecar_cold_start.py.

import importlib
import sys


def test_module_import_does_not_load_soundfile_or_sounddevice(monkeypatch):
    for mod in list(sys.modules):
        if mod in ("soundfile", "sounddevice") or mod.startswith(
            ("soundfile.", "sounddevice.")
        ):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.delitem(sys.modules, "speechtotext.ingest.mic", raising=False)

    importlib.import_module("speechtotext.ingest.mic")

    assert "soundfile" not in sys.modules, (
        "speechtotext.ingest.mic must defer `import soundfile` until first record call "
        "so sidecar first-request stays fast"
    )
    assert "sounddevice" not in sys.modules, (
        "speechtotext.ingest.mic must defer `import sounddevice` until first record call "
        "so sidecar first-request stays fast"
    )
