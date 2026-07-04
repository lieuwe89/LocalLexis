"""Pull hub transcripts into the local synced dir.

One round = one HTTP call. First sync (cursor 0) uses ``/sync/snapshot``;
after that ``/sync/since/{cursor}``. Docs land as
``<app-data>/hub/synced/<id>.json`` — the same id-as-filename-stem layout
the hub uses, so the local LibraryDB indexes them exactly like local
transcripts. The wire-injected ``id`` key is stripped before writing
(filename stem is canonical; see routes_sync.py "Mobile clients require
it to key rows").

The periodic loop lives in the sidecar runtime (hub_runtime.py), not
here — this module stays synchronous and unit-testable.
"""

from __future__ import annotations

import json
from pathlib import Path

from speechtotext.client import state as state_module
from speechtotext.client.paths import synced_dir


def pull_once(hub_client) -> list[Path]:
    st = state_module.load()
    if st is None:
        return []
    if st.cursor <= 0.0:
        payload = hub_client.get_json("/sync/snapshot")
    else:
        payload = hub_client.get_json(f"/sync/since/{st.cursor}")

    root = synced_dir()
    written: list[Path] = []
    for doc in payload.get("transcripts", []):
        doc = dict(doc)
        tid = doc.pop("id", None)
        if not tid:
            continue
        root.mkdir(parents=True, exist_ok=True)
        dest = root / f"{tid}.json"
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(dest)
        written.append(dest)

    new_cursor = float(payload.get("cursor", st.cursor))
    if new_cursor > st.cursor:
        state_module.update_cursor(new_cursor)
    return written
