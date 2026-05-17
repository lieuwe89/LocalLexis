"""Background warmup tasks the sidecar runs on startup.

The only one today is a microphone permission primer: open and immediately
close an audio input stream so macOS shows its permission dialog (and
PortAudio finishes initializing) before the user clicks Record. Without
this the first recording session loses its first second or two while the
permission sheet is up.
"""

from __future__ import annotations

import logging
import threading

_log = logging.getLogger(__name__)


def _warm() -> None:
    try:
        import sounddevice as sd  # heavy import; do it lazily off the main thread

        # 1 frame at 16 kHz mono. Enough to trigger the OS permission flow
        # and prime PortAudio's input device; not enough to be perceptible.
        with sd.InputStream(samplerate=16000, channels=1, blocksize=1):
            pass
    except Exception as exc:  # noqa: BLE001
        # No mic, permission denied, no default input device — all fine.
        # We're best-effort: the real recording flow will surface errors.
        _log.info("mic warmup skipped: %s: %s", type(exc).__name__, exc)


def warm_microphone_in_background() -> None:
    threading.Thread(target=_warm, name="mic-warmup", daemon=True).start()
