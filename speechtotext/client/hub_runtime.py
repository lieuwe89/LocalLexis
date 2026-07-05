"""Background runtime for a joined hub: uploader sweep + sync pull.

Single daemon thread; each cycle sweeps the outbox then pulls sync.
``poke()`` wakes the thread immediately (used right after an enqueue so
uploads don't wait for the next period). ``stop()`` sets the event and
joins the thread.

No FastAPI imports here — the sidecar wires callbacks (routes/app layer)
to update job records and re-index the library.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from speechtotext.client import identity as identity_module
from speechtotext.client import state as state_module
from speechtotext.client import sync_puller, upload_queue
from speechtotext.client.hub_client import HubClient
from speechtotext.client.upload_queue import OutboxEntry

DEFAULT_PERIOD_S = 30.0


def _default_factory(st, ident) -> HubClient:
    return HubClient(st.hub_url, st.device_id, ident.signing_key())


class HubRuntime:
    def __init__(
        self,
        *,
        hub_client_factory: Callable = _default_factory,
        on_entry_sent: Callable[[OutboxEntry], None] | None = None,
        on_synced: Callable[[list[Path]], None] | None = None,
        period_s: float = DEFAULT_PERIOD_S,
    ) -> None:
        self._factory = hub_client_factory
        self._on_entry_sent = on_entry_sent
        self._on_synced = on_synced
        self._period = period_s
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None
        self._last_sync_at: float | None = None

    # -- lifecycle -------------------------------------------------------
    def joined(self) -> bool:
        return state_module.load() is not None

    def start(self) -> None:
        if (self._thread is not None and self._thread.is_alive()) or not self.joined():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="hub-runtime", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def poke(self) -> None:
        self._wake.set()

    # -- work ------------------------------------------------------------
    def enqueue_upload(self, audio_path: Path, *, job_id: str | None) -> None:
        upload_queue.enqueue(audio_path, job_id=job_id)

    def status(self) -> dict:
        st = state_module.load()
        if st is None:
            return {"joined": False}
        return {
            "joined": True,
            "hub_url": st.hub_url,
            "workspace_id": st.workspace_id,
            "device_id": st.device_id,
            "device_name": st.device_name,
            "cursor": st.cursor,
            "pending_uploads": len(upload_queue.pending()),
            "last_error": self._last_error,
            "last_sync_at": self._last_sync_at,
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            # Clear BEFORE the cycle's work, not after wait(): a poke()
            # that lands during the work phase must not be wiped by a
            # later clear, or the enqueue it accompanied could sit in the
            # outbox for a full period. With clear-at-top, any poke set
            # after this line either wakes the wait() below immediately
            # or is consumed by the next cycle's work — never lost.
            self._wake.clear()
            client = None
            try:
                st = state_module.load()
                ident = identity_module.load()
                if st is None or ident is None:
                    break  # left the hub while running
                client = self._factory(st, ident)
                sent = upload_queue.sweep(client)
                if self._on_entry_sent:
                    for entry in sent:
                        self._on_entry_sent(entry)
                written = sync_puller.pull_once(client)
                if written and self._on_synced:
                    self._on_synced(written)
                self._last_error = None
                self._last_sync_at = time.time()
            except (FileNotFoundError, OSError):
                # Racing with a concurrent leave_hub() deleting the key/state
                # files mid-cycle — treat exactly like "left the hub while
                # running": stop looping, no error to report (there's no
                # hub relationship left to report an error about).
                break
            except Exception as exc:  # network errors -> retry next cycle
                self._last_error = f"{type(exc).__name__}: {exc}"
            finally:
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass
            self._wake.wait(timeout=self._period)
