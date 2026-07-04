"""Joined-hub state: ``<app-data>/hub/client_state.json``.

Existence of this file == "this install is joined to a hub". The sync
cursor lives here (not in library.db) because it belongs to the hub
relationship, which `leave()` must delete atomically with the rest.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from speechtotext.client.paths import hub_dir


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


def save(st: ClientState) -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(st)), encoding="utf-8")
    tmp.replace(path)


def load() -> ClientState | None:
    path = _state_file()
    if not path.exists():
        return None
    return ClientState(**json.loads(path.read_text(encoding="utf-8")))


def update_cursor(cursor: float) -> None:
    st = load()
    if st is None:
        return
    st.cursor = cursor
    save(st)


def delete() -> None:
    try:
        _state_file().unlink()
    except FileNotFoundError:
        pass
