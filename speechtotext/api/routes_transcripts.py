from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from speechtotext.api.auth import verify_device_signature
from speechtotext.api.crdt import (
    OpRequest,
    TranscriptState,
    merge_op,
)
from speechtotext.api.library import find_sidecar
from speechtotext.api.workspace import (
    bump_lamport_to,
    get_lamport,
    get_workspace_id,
)
from speechtotext.relabel import relabel

router = APIRouter()


class PatchOpBody(BaseModel):
    """Incoming CRDT op for ``PATCH /transcripts/{tid}``.

    The hub assigns the authoritative ``lamport`` on apply and stamps
    the verified ``device_id`` from the signed request — clients cannot
    supply a device attribution. Clients pass the highest lamport they
    have observed so far so the hub can avoid demoting them.
    """

    op: str = Field(description="Op type. v1 supports 'relabel'.")
    key: str = Field(description="Dotted key, e.g. 'speakers.SPEAKER_00'.")
    value: Any = Field(description="New value at the key.")
    lamport_observed: int = Field(
        ge=0,
        description="Highest Lamport the client has seen for this workspace.",
    )

    model_config = {"extra": "ignore"}


class PatchResult(BaseModel):
    """Result of a successful PATCH op.

    ``applied`` is the canonical op record (with hub-assigned Lamport
    and timestamp). ``speakers`` / ``_clocks`` / ``_history`` mirror
    the on-disk transcript's new state. ``lamport_assigned`` lets the
    client advance its observed counter.
    """

    applied: dict
    speakers: dict
    clocks: dict = Field(alias="_clocks")
    history: list[dict] = Field(alias="_history")
    lamport_assigned: int

    model_config = {"populate_by_name": True}


def _atomic_write_json(path: Path, doc: dict) -> None:
    """Same atomic-tmp-then-rename pattern as ``writer._atomic_write``."""
    content = json.dumps(doc, indent=2, ensure_ascii=False)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _get_transcript_lock(state, tid: str) -> threading.Lock:
    """Return the per-transcript write lock, creating it on first use.

    A small dict-level lock guards the lazy creation so two concurrent
    requests for the same transcript get the same lock object.
    """
    with state.transcript_locks_dict_lock:
        lock = state.transcript_locks.get(tid)
        if lock is None:
            lock = threading.Lock()
            state.transcript_locks[tid] = lock
        return lock


@router.get("/transcripts")
def list_transcripts(
    request: Request,
    q: str | None = Query(default=None, description="full-text search query"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict]:
    db = request.app.state.library_db
    # Reconcile before responding so the user sees rows matching disk. The
    # reconciler skips the walk when no library dir's mtime changed, so
    # search-as-you-type doesn't stat every file on every keystroke.
    request.app.state.library_reconciler.reconcile(request.app.state.library_dirs)
    if q:
        return db.search(q, limit=limit)
    return db.list(limit=limit)


@router.get("/transcripts/{tid}")
def get_transcript(tid: str, request: Request) -> dict:
    db = request.app.state.library_db
    p = db.get_path(tid) or find_sidecar(request.app.state.library_dirs, tid)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")
    doc = json.loads(p.read_text(encoding="utf-8"))
    txt = p.with_suffix(".txt")
    doc["paths"] = {
        "json": str(p),
        **({"txt": str(txt)} if txt.is_file() else {}),
    }
    return doc


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _forward_relabel_to_hub(
    request: Request, tid: str, mapping: dict[str, str], p: Path
) -> dict:
    """Relabel a hub-origin transcript by forwarding one signed CRDT op
    per speaker to the hub. The hub applies LWW and the updated doc comes
    back on the next sync pull, so we deliberately do NOT write the local
    synced file here (a local write would be clobbered by that pull).

    Ops are forwarded one-per-speaker and are NOT atomic: a mid-batch hub
    failure may leave earlier speakers already applied on the hub. The whole
    mapping is safe to retry (CRDT relabel is last-writer-wins per key)."""
    from speechtotext.api import routes_client
    from speechtotext.client import identity as _identity
    from speechtotext.client import state as _state
    from speechtotext.client.hub_client import HubClient

    st = _state.load()
    ident = _identity.load()
    if st is None or ident is None:
        raise HTTPException(status_code=409, detail="hub state missing")

    # Seed lamport_observed from the highest clock we've synced for this
    # transcript, then chain the hub-assigned lamport across the batch so
    # successive ops in one relabel aren't demoted.
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        doc = {}
    observed = 0
    for c in (doc.get("_clocks") or {}).values():
        if isinstance(c, dict):
            observed = max(observed, int(c.get("lamport", 0)))

    hub = HubClient(
        st.hub_url, st.device_id, ident.signing_key(),
        transport=routes_client.sync_test_transport(),
    )
    try:
        for speaker_id, new_name in mapping.items():
            try:
                result = hub.patch_json(f"/transcripts/{tid}", {
                    "op": "relabel",
                    "key": f"speakers.{speaker_id}",
                    "value": new_name,
                    "lamport_observed": observed,
                })
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"hub rejected relabel: {exc.response.status_code}",
                ) from exc
            except httpx.HTTPError as exc:
                raise HTTPException(
                    status_code=502, detail=f"cannot reach hub: {exc}"
                ) from exc
            la = result.get("lamport_assigned")
            if isinstance(la, int):
                observed = max(observed, la)
    finally:
        hub.close()

    # Pull the hub's authoritative version back promptly so the UI reflects
    # the relabel without waiting a full sync period.
    if runtime := getattr(request.app.state, "hub_runtime", None):
        runtime.poke()
    return {"ok": True, "forwarded": True}


@router.patch("/transcripts/{tid}/relabel")
def patch_relabel(tid: str, mapping: dict[str, str], request: Request) -> dict:
    db = request.app.state.library_db
    p = db.get_path(tid) or find_sidecar(request.app.state.library_dirs, tid)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")

    # Hub-origin transcripts (under the synced dir) are relabeled by
    # forwarding signed CRDT ops to the hub; the change round-trips back on
    # the next sync pull. A local rewrite here would be clobbered by that
    # pull. Do this OUTSIDE the per-tid lock: the forwarded CRDT PATCH takes
    # its own lock, and in the loopback-self case holding ours would deadlock.
    from speechtotext.client.paths import synced_dir
    runtime = getattr(request.app.state, "hub_runtime", None)
    if runtime is not None and runtime.joined() and _is_under(p, synced_dir()):
        return _forward_relabel_to_hub(request, tid, mapping, p)

    # Take the same per-transcript lock as the CRDT PATCH op: relabel does a
    # read-modify-write on the sidecar JSON, so without it a concurrent
    # PATCH /transcripts/{tid} could be clobbered (and vice versa).
    lock = _get_transcript_lock(request.app.state, tid)
    with lock:
        try:
            relabel(p, mapping)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        # speaker_labels participate in FTS, so reindex this row after relabel
        db.upsert_path(p)
    return {"ok": True}


@router.patch("/transcripts/{tid}", response_model=PatchResult)
def patch_transcript_op(
    tid: str,
    body: PatchOpBody,
    request: Request,
    device_id: str = Depends(verify_device_signature),
) -> PatchResult:
    """Apply a CRDT op to a transcript.

    Unlike ``/transcripts/{tid}/relabel`` (which takes a bulk mapping
    and applies it locally with no clock awareness), this endpoint is
    the canonical entry point for device-driven edits that participate
    in multi-device sync. The hub assigns the Lamport, runs LWW per
    key, and records the op in the transcript's ``_history``.
    """
    db = request.app.state.library_db
    p = db.get_path(tid) or find_sidecar(request.app.state.library_dirs, tid)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")

    # Serialise read-modify-write so two paired devices PATCHing the
    # same transcript can't both read the same on-disk state and have
    # the second writer clobber the first. The lock is per-tid so
    # different transcripts still PATCH in parallel.
    lock = _get_transcript_lock(request.app.state, tid)
    with lock:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=500, detail=f"failed to read transcript: {exc}"
            )

        state = TranscriptState.from_json(doc)
        op_request = OpRequest(
            op=body.op,
            key=body.key,
            value=body.value,
            device=device_id,
            lamport_observed=body.lamport_observed,
        )
        try:
            new_state, new_lamport, applied_op = merge_op(
                state, op_request, get_lamport()
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        # Persist new counter before writing the file so a crash between
        # write and counter-update is recoverable from the transcript log.
        bump_lamport_to(new_lamport)

        # Merge CRDT state back into the full doc and write atomically.
        # Stamp workspace_id if the transcript pre-dates the v2 schema.
        if not doc.get("_workspace_id"):
            doc["_workspace_id"] = get_workspace_id()
        doc["speakers"] = dict(new_state.speakers)
        doc["_clocks"] = {k: asdict(c) for k, c in new_state.clocks.items()}
        doc["_history"] = [asdict(op) for op in new_state.history]
        _atomic_write_json(p, doc)

    # speaker_labels participate in FTS, so reindex.
    db.upsert_path(p)

    return PatchResult(
        applied=asdict(applied_op),
        speakers=dict(new_state.speakers),
        _clocks={k: asdict(c) for k, c in new_state.clocks.items()},
        _history=[asdict(op) for op in new_state.history],
        lamport_assigned=new_lamport,
    )
