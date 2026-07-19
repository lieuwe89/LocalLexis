"""Joined-hub state: ``<app-data>/hub/client_state.json``.

Existence of this file == "this install is joined to a hub". The sync
cursor lives here (not in library.db) because it belongs to the hub
relationship, which `leave()` must delete atomically with the rest.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, fields

from speechtotext.client.paths import hub_dir

# Serializes read-modify-write cycles: HubRuntime's periodic update_cursor
# and the migrate job's update_fields(migrated_at=...) run on different
# threads; without this, one save can silently clobber the other's field.
# ponytail: process-wide lock; fine while one sidecar process owns the file.
_lock = threading.Lock()


def _state_file():
    return hub_dir() / "client_state.json"


@dataclass
class ClientState:
    hub_url: str
    workspace_id: str
    device_id: str
    device_name: str
    tls_spki_b64: str | None
    cursor: float
    migrated_at: float | None = None
    offline_capture: str = "local"  # "local" | "queue"


def _save_unlocked(st: ClientState) -> None:
    # Atomic tmp-then-rename, but deliberately NO fsync (unlike the device
    # key in identity.py). This state is fully recoverable: a lost cursor
    # just re-pulls sync from an older point (idempotent), and the rest is
    # re-derivable by re-pairing. The device key is unrecoverable, so it
    # pays for the fsync; this does not.
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(st)), encoding="utf-8")
    tmp.replace(path)


def save(st: ClientState) -> None:
    with _lock:
        _save_unlocked(st)


def load() -> ClientState | None:
    path = _state_file()
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    # Drop keys this version doesn't know: a state file written by a NEWER
    # version must never brick startup (the v0.18.0 migration fields crashed
    # the older bundled sidecar exactly this way). Unknown keys are preserved
    # on disk until the next save() by a version that knows them — acceptable:
    # save() rewrites from this dataclass, and newer-version fields are
    # re-derivable (migrated_at re-set by a clean sweep, settings re-chosen).
    known = {f.name for f in fields(ClientState)}
    return ClientState(**{k: v for k, v in data.items() if k in known})


def update_cursor(cursor: float) -> None:
    update_fields(cursor=cursor)


def update_fields(**kwargs) -> None:
    # Lock spans the whole read-modify-write so a concurrent updater
    # (runtime cursor save vs. migrate job's migrated_at) can't clobber
    # the other's field with a stale load.
    with _lock:
        st = load()
        if st is None:
            return
        for k, v in kwargs.items():
            setattr(st, k, v)
        _save_unlocked(st)


def delete() -> None:
    try:
        _state_file().unlink()
    except FileNotFoundError:
        pass
