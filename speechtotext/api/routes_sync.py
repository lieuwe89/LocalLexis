"""Multi-device sync endpoints — snapshot + delta.

Wire shape::

    GET /sync/snapshot
        -> { workspace_id, cursor, transcripts: [...] }

    GET /sync/since/{cursor}
        -> { workspace_id, cursor, transcripts: [...] }

``cursor`` is a numeric value: the largest ``json_mtime`` (unix epoch
seconds, float, sub-second precision where the filesystem supports it)
present in the response. A device reads ``cursor``, stores it locally,
and passes the same value back on the next ``/sync/since`` call to
receive only what changed in between.

Why mtime, not Lamport?
-----------------------

The workspace-wide Lamport counter tracks per-field CRDT op ordering,
but a freshly-transcribed transcript (no edits yet) has all clocks at
0. A Lamport-based cursor would miss those. ``json_mtime`` advances
every time the writer atomically replaces a sidecar, which captures
both new transcripts and CRDT-modified ones uniformly. The two
concepts live side-by-side: clocks order edits *within* a transcript;
mtime orders *which transcripts changed*.

Authorisation
-------------

Both endpoints require a paired-device signature
(:func:`speechtotext.api.auth.verify_device_signature`). Same shape
as ``PATCH /transcripts/{id}``: ``X-Device-Id`` + ``X-Signature-B64``
over METHOD + "\\n" + PATH + "\\n" + body.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from speechtotext.api.auth import verify_device_signature
from speechtotext.api.workspace import get_workspace_id

router = APIRouter()


class SyncResponse(BaseModel):
    workspace_id: str
    cursor: float = Field(
        description="Largest json_mtime present in this response. "
        "Pass back to /sync/since to fetch deltas after.",
    )
    transcripts: list[dict[str, Any]] = Field(
        description="Full transcript JSON docs. Empty if nothing changed."
    )


def _build_delta(
    request: Request, *, since: float, limit: int = 10000, offset: int = 0
) -> SyncResponse:
    db = request.app.state.library_db
    # Reconcile before responding so the delta reflects disk. The reconciler
    # skips the walk entirely when no library dir's mtime changed, so idle
    # device polls don't stat every transcript file each time.
    # Snapshot the dir set — background daemons (_on_complete_dir) mutate it
    # via .add() off-thread, and set() is an atomic C-level copy, so the
    # reconciler iterates a private copy that can't grow mid-iteration.
    request.app.state.library_reconciler.reconcile(set(request.app.state.library_dirs))

    rows = db.list_since(since, limit=limit, offset=offset)

    new_cursor = since
    docs: list[dict[str, Any]] = []
    for row in rows:
        path = Path(row["json_path"])
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Index references a file that's gone or corrupt; skip.
            continue
        # Surface the transcript id (json file stem) on the wire — the
        # index keys on it (json_path.stem) but it isn't inside the doc.
        # Mobile clients require it to key rows.
        docs.append({**doc, "id": path.stem})
        # Advance cursor monotonically. Rows are returned mtime-ASC so
        # the last value wins, but use max() defensively.
        new_cursor = max(new_cursor, float(row["json_mtime"]))

    # If nothing changed but the library has content, surface the
    # library's current max as the cursor so the device's local
    # cursor doesn't lag forever on idle workspaces.
    if not docs:
        max_seen = db.max_mtime()
        new_cursor = max(new_cursor, max_seen)

    return SyncResponse(
        workspace_id=get_workspace_id(),
        cursor=new_cursor,
        transcripts=docs,
    )


@router.get("/sync/snapshot", response_model=SyncResponse)
def sync_snapshot(
    request: Request,
    device_id: str = Depends(verify_device_signature),
    limit: int = Query(10000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
) -> SyncResponse:
    """Return transcripts in the workspace, oldest-mtime first.

    Used by new devices on first connect. For large libraries, page with
    ``?limit=N&offset=M``: walk ``offset`` 0, N, 2N, … until a page returns
    fewer than ``limit`` rows, then use the *last* page's ``cursor`` as the
    starting point for subsequent ``/sync/since`` polls. Default ``limit``
    returns the whole library in one response.
    """
    return _build_delta(request, since=0.0, limit=limit, offset=offset)


@router.get("/sync/since/{cursor}", response_model=SyncResponse)
def sync_since(
    cursor: float,
    request: Request,
    device_id: str = Depends(verify_device_signature),
    limit: int = Query(10000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
) -> SyncResponse:
    """Return transcripts whose mtime is strictly greater than ``cursor``.

    Supports the same ``limit``/``offset`` paging as ``/sync/snapshot`` for
    unusually large deltas.
    """
    return _build_delta(request, since=cursor, limit=limit, offset=offset)
