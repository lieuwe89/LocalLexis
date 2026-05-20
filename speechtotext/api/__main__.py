"""Module entry point.

The Tauri shell normally spawns this as the bundled sidecar, in which
case the default ``run`` entry binds 127.0.0.1 on a random port and
prints a stdout handshake so the Rust side can discover the URL.

When the user enables "hub mode" the Tauri shell flips
``LOCALLEXIS_HEADLESS=1`` before spawning; we route to ``headless``
instead so the sidecar binds 0.0.0.0 on a stable port, optionally
with TLS, and skips the stdout handshake. The same env var lets the
``locallexis-hub`` console script (Docker / systemd) reuse the same
binary without a separate Python module.
"""

from __future__ import annotations

import os

from speechtotext.api.server import headless, run


def _is_headless() -> bool:
    return os.environ.get("LOCALLEXIS_HEADLESS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


if __name__ == "__main__":
    if _is_headless():
        headless()
    else:
        run()
