from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
from contextvars import ContextVar
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from speechtotext.api.auth import (
    verify_admin_or_device,
    verify_admin_or_device_or_anonymous,
)
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
from speechtotext.rag import embedder as rag_embedder
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


def _rewrite_txt_sidecar(json_path: Path, doc: dict) -> None:
    """Regenerate the human-readable .txt next to the JSON after an edit.

    Mirrors writer.format_txt but works on the raw doc dict so we don't
    round-trip through the Transcript dataclass (which requires fields a
    minimal/legacy doc may lack).
    """
    from speechtotext.writer import _format_timestamp

    speakers = doc.get("speakers") or {}
    lines = []
    for seg in doc.get("segments") or []:
        spk = seg.get("speaker", "")
        display = speakers.get(spk, spk)
        lines.append(
            f"[{_format_timestamp(float(seg.get('start', 0.0)))}] {display}: {seg.get('text', '')}"
        )
    txt = json_path.with_suffix(".txt")
    content = "\n".join(lines) + ("\n" if lines else "")
    tmp = txt.with_suffix(txt.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, txt)


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
    fuzzy: bool = Query(
        default=False,
        description="also match phonetically; ignored when semantic=1",
    ),
    sort: str = Query(
        default="relevance",
        pattern="^(relevance|date)$",
        description="result ordering; ignored when semantic=1",
    ),
    semantic: bool = Query(default=False, description="match by meaning (embeddings)"),
    _actor: str = Depends(verify_admin_or_device_or_anonymous),
) -> list[dict]:
    db = request.app.state.library_db
    # Reconcile before responding so the user sees rows matching disk. The
    # reconciler skips the walk when no library dir's mtime changed, so
    # search-as-you-type doesn't stat every file on every keystroke.
    # Snapshot the dir set (atomic C-level copy) so a background .add() from
    # _on_complete_dir can't grow it mid-iteration inside reconcile.
    request.app.state.library_reconciler.reconcile(set(request.app.state.library_dirs))
    if q and semantic:
        # Joined laptops delegate to the hub instead of embedding locally —
        # the hub holds the full library + the embedding model.
        runtime = getattr(request.app.state, "hub_runtime", None)
        if runtime is not None and runtime.joined():
            forwarded = _forward_semantic_to_hub(q, limit)
            if forwarded is not None:
                return forwarded
            # else: a forward is already in progress on this call stack (we
            # ARE the hub receiving that forwarded query) — embed locally.
        # First call may block for the one-time model download (see rag/embedder.py).
        try:
            qvec = rag_embedder.get_embedder().embed([q])[0]
        except rag_embedder.EmbedderError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        items = db.semantic_search(qvec, rag_embedder.EMBED_MODEL, limit=limit)
        from speechtotext.rag.highlight import mark_hits
        mark_hits(items, qvec, rag_embedder.get_embedder().embed)
        return items
    if q:
        return db.search(q, limit=limit, fuzzy=fuzzy, sort=sort)
    return db.list(limit=limit)


@router.get("/transcripts/{tid}")
def get_transcript(tid: str, request: Request) -> dict:
    db = request.app.state.library_db
    p = db.get_path(tid) or find_sidecar(set(request.app.state.library_dirs), tid)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")
    doc = json.loads(p.read_text(encoding="utf-8"))
    txt = p.with_suffix(".txt")
    doc["paths"] = {
        "json": str(p),
        **({"txt": str(txt)} if txt.is_file() else {}),
    }
    return doc


@router.delete("/transcripts/{tid}")
def delete_transcript(tid: str, request: Request) -> dict:
    from speechtotext.api import trash as trash_mod
    from speechtotext.client.paths import synced_dir

    db = request.app.state.library_db
    p = db.get_path(tid) or find_sidecar(set(request.app.state.library_dirs), tid)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")
    runtime = getattr(request.app.state, "hub_runtime", None)
    if runtime is not None and runtime.joined() and _is_under(p, synced_dir()):
        raise HTTPException(
            status_code=409,
            detail="hub-synced transcript: delete it on the hub instead",
        )
    lock = _get_transcript_lock(request.app.state, tid)
    with lock:
        trash_mod.trash_transcript(p)
        db.delete_by_path(p)
    return {"ok": True, "trashed": True}


_FILE_FORMATS = {"json": "application/json", "txt": "text/plain"}


@router.get("/transcripts/{tid}/file/{fmt}")
def get_transcript_file(
    tid: str,
    fmt: str,
    request: Request,
    _actor: str = Depends(verify_admin_or_device_or_anonymous),
):
    media_type = _FILE_FORMATS.get(fmt)
    if media_type is None:
        raise HTTPException(status_code=404, detail=f"unknown format: {fmt}")
    db = request.app.state.library_db
    p = db.get_path(tid) or find_sidecar(set(request.app.state.library_dirs), tid)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")
    target = p if fmt == "json" else p.with_suffix(f".{fmt}")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"no .{fmt} file for transcript: {tid}")
    return FileResponse(target, media_type=media_type, filename=target.name)


_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


@router.get("/transcripts/{tid}/audio")
def get_transcript_audio(
    tid: str,
    request: Request,
    _actor: str = Depends(verify_admin_or_device_or_anonymous),
):
    db = request.app.state.library_db
    p = db.get_path(tid) or find_sidecar(set(request.app.state.library_dirs), tid)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"failed to read transcript: {exc}")
    audio_raw = doc.get("audio_path")
    audio = Path(audio_raw) if audio_raw else None
    if audio is None or not audio.is_file():
        runtime = getattr(request.app.state, "hub_runtime", None)
        if runtime is not None and runtime.joined():
            proxied = _stream_audio_from_hub(tid, request.headers.get("range"))
            if proxied is not None:
                return proxied
        raise HTTPException(status_code=404, detail="audio file not found on server")

    media_type = mimetypes.guess_type(audio.name)[0] or "application/octet-stream"
    size = audio.stat().st_size
    range_header = request.headers.get("range")
    if range_header:
        m = _RANGE_RE.match(range_header.strip())
        if not m or (not m.group(1) and not m.group(2)):
            raise HTTPException(status_code=416, detail="malformed Range header")
        start = int(m.group(1)) if m.group(1) else None
        end = int(m.group(2)) if m.group(2) else None
        if start is None:          # suffix form: bytes=-N (last N bytes)
            start = max(0, size - (end or 0))
            end = size - 1
        elif end is None or end >= size:
            end = size - 1
        if start >= size or start > end:
            raise HTTPException(status_code=416, detail="range out of bounds")
        with audio.open("rb") as fh:
            fh.seek(start)
            chunk = fh.read(end - start + 1)
        return Response(
            content=chunk,
            status_code=206,
            media_type=media_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Accept-Ranges": "bytes",
            },
        )
    return FileResponse(
        audio, media_type=media_type, headers={"Accept-Ranges": "bytes"}
    )


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


# Guards against unbounded self-forwarding. Hub-and-spoke is the only
# supported topology (see docs/superpowers/plans/2026-07-04-hub-client-mode.md);
# nothing stops a single process from being simultaneously "joined" and the
# target of its own forwarded op (this happens for real in tests that pair a
# node to itself via an ASGI-loopback transport, and would also happen if a
# hub were ever misconfigured to join itself or a downstream peer). Without
# this guard such a request recurses through the full ASGI stack until
# RecursionError, which is expensive enough to look like a hang. A ContextVar
# (not a plain module global) keeps the flag correctly scoped to the request
# that set it even if the ASGI server ever runs requests concurrently on the
# same thread (e.g. under an async event loop).
_forwarding_in_progress: ContextVar[bool] = ContextVar(
    "_forwarding_in_progress", default=False
)


def _stream_audio_from_hub(tid: str, range_header: str | None):
    """Migrated transcripts keep their audio on the hub; stream it through
    with Range passthrough so seeking works. Returns None when this process
    IS the hub receiving its own forward (recursion guard) — caller 404s."""
    from urllib.parse import quote

    from fastapi.responses import StreamingResponse

    from speechtotext.api import routes_client
    from speechtotext.client import identity as _identity
    from speechtotext.client import state as _state
    from speechtotext.client.hub_client import HubClient

    if _forwarding_in_progress.get():
        return None
    st = _state.load()
    ident = _identity.load()
    if st is None or ident is None:
        raise HTTPException(status_code=503, detail="hub state missing")
    hub = HubClient(
        st.hub_url, st.device_id, ident.signing_key(),
        transport=routes_client.sync_test_transport(), timeout=30.0,
    )
    token = _forwarding_in_progress.set(True)
    try:
        extra = {"Range": range_header} if range_header else None
        resp = hub.stream_get(
            f"/transcripts/{quote(tid, safe='')}/audio", extra
        )
    except Exception as exc:
        _forwarding_in_progress.reset(token)
        hub.close()
        raise HTTPException(
            status_code=503, detail=f"hub unreachable for audio: {exc}"
        ) from exc
    # Reset right after the send: on a loopback transport the hub-side handler
    # runs DURING stream_get, which is the recursion window; the client-side
    # body iteration below happens after the response already started.
    _forwarding_in_progress.reset(token)

    if resp.status_code >= 400:
        code = resp.status_code
        resp.close()
        hub.close()
        raise HTTPException(status_code=code, detail="hub could not serve audio")

    passthrough = {
        k: v for k, v in resp.headers.items()
        if k.lower() in ("content-type", "content-length", "content-range", "accept-ranges")
    }

    def _iter():
        try:
            yield from resp.iter_bytes()
        finally:
            resp.close()
            hub.close()

    return StreamingResponse(
        _iter(), status_code=resp.status_code, headers=passthrough,
        media_type=resp.headers.get("content-type"),
    )


def _forward_op_to_hub(
    request: Request, tid: str, ops: list[dict], p: Path
) -> dict | None:
    """Forward CRDT ops for a hub-synced transcript to the hub.

    The hub applies LWW and the updated doc comes back on the next sync
    pull, so we deliberately do NOT write the local synced file here (a
    local write would be clobbered by that pull).

    Ops are forwarded one at a time and are NOT atomic: a mid-batch hub
    failure may leave earlier ops already applied on the hub. Each op is
    safe to retry individually (CRDT merge is last-writer-wins per key).
    Returns the last op's hub response, or None if forwarding was skipped
    because a forward is already in progress on this call stack (the
    caller should fall back to applying the op locally in that case)."""
    if _forwarding_in_progress.get():
        return None
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
    # successive ops aren't demoted.
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
    result: dict = {}
    token = _forwarding_in_progress.set(True)
    try:
        for op_body in ops:
            try:
                result = hub.patch_json(f"/transcripts/{tid}", {
                    **op_body,
                    "lamport_observed": observed,
                })
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"hub rejected op: {exc.response.status_code}",
                ) from exc
            except httpx.HTTPError as exc:
                raise HTTPException(
                    status_code=502, detail=f"cannot reach hub: {exc}"
                ) from exc
            la = result.get("lamport_assigned")
            if isinstance(la, int):
                observed = max(observed, la)
    finally:
        _forwarding_in_progress.reset(token)
        hub.close()

    # Pull the hub's authoritative version back promptly so the UI reflects
    # the change without waiting a full sync period.
    if runtime := getattr(request.app.state, "hub_runtime", None):
        runtime.poke()
    return result


def _forward_semantic_to_hub(q: str, limit: int) -> list[dict] | None:
    """Joined laptops delegate semantic search to the hub: the hub holds
    the full library + the embedding model. Tids match the synced copies,
    so jump-to-segment works unchanged.

    Returns None (instead of forwarding) if a forward is already in
    progress on this call stack — see ``_forwarding_in_progress``. The
    caller should fall back to embedding locally in that case."""
    if _forwarding_in_progress.get():
        return None
    from urllib.parse import quote as _quote

    from speechtotext.api import routes_client
    from speechtotext.client import identity as _identity
    from speechtotext.client import state as _state
    from speechtotext.client.hub_client import HubClient

    st = _state.load()
    ident = _identity.load()
    if st is None or ident is None:
        raise HTTPException(status_code=503, detail="hub state missing")
    hub = HubClient(
        st.hub_url, st.device_id, ident.signing_key(),
        transport=routes_client.sync_test_transport(),
        # ponytail: hub cold-start (first-ever embed downloads the model) can
        # exceed this — bump if it bites; the hub normally warms at startup
        # via its EmbedWorker.
        timeout=5.0,
    )
    token = _forwarding_in_progress.set(True)
    try:
        return hub.get_json(
            f"/transcripts?q={_quote(q, safe='')}&semantic=1&limit={limit}"
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"hub rejected semantic search: {exc.response.status_code}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"hub unreachable for semantic search: {exc}"
        ) from exc
    finally:
        _forwarding_in_progress.reset(token)
        hub.close()


def _forward_relabel_to_hub(
    request: Request, tid: str, mapping: dict[str, str], p: Path
) -> dict | None:
    """Relabel a hub-origin transcript by forwarding one signed CRDT op
    per speaker to the hub. The hub applies LWW and the updated doc comes
    back on the next sync pull, so we deliberately do NOT write the local
    synced file here (a local write would be clobbered by that pull).

    Ops are forwarded one-per-speaker and are NOT atomic: a mid-batch hub
    failure may leave earlier speakers already applied on the hub. The whole
    mapping is safe to retry (CRDT relabel is last-writer-wins per key).

    Returns ``None`` (instead of forwarding) if a forward is already in
    progress on this call stack — see ``_forwarding_in_progress``. Callers
    should fall back to applying the mapping locally in that case."""
    ops = [
        {"op": "relabel", "key": f"speakers.{sid}", "value": name}
        for sid, name in mapping.items()
    ]
    result = _forward_op_to_hub(request, tid, ops, p)
    if result is None:
        return None
    return {"ok": True, "forwarded": True}


@router.patch("/transcripts/{tid}/relabel")
def patch_relabel(tid: str, mapping: dict[str, str], request: Request) -> dict:
    db = request.app.state.library_db
    p = db.get_path(tid) or find_sidecar(set(request.app.state.library_dirs), tid)
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
        result = _forward_relabel_to_hub(request, tid, mapping, p)
        if result is not None:
            return result
        # else: a forward is already in progress on this call stack (we ARE
        # the hub receiving that forwarded op) — apply locally below.

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
    device_id: str = Depends(verify_admin_or_device),
) -> PatchResult:
    """Apply a CRDT op to a transcript.

    Unlike ``/transcripts/{tid}/relabel`` (which takes a bulk mapping
    and applies it locally with no clock awareness), this endpoint is
    the canonical entry point for device-driven edits that participate
    in multi-device sync. The hub assigns the Lamport, runs LWW per
    key, and records the op in the transcript's ``_history``.
    """
    db = request.app.state.library_db
    p = db.get_path(tid) or find_sidecar(set(request.app.state.library_dirs), tid)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail=f"transcript not found: {tid}")

    # Hub-origin transcripts (under the synced dir) have this op forwarded to
    # the hub instead of applied locally; the change round-trips back on the
    # next sync pull. A local write here would be clobbered by that pull. Do
    # this OUTSIDE the per-tid lock: the forwarded CRDT PATCH takes its own
    # lock, and in the loopback-self case holding ours would deadlock.
    from speechtotext.client.paths import synced_dir
    runtime = getattr(request.app.state, "hub_runtime", None)
    if runtime is not None and runtime.joined() and _is_under(p, synced_dir()):
        resp = _forward_op_to_hub(
            request, tid,
            [{"op": body.op, "key": body.key, "value": body.value}], p,
        )
        if resp is not None:
            return PatchResult.model_validate(resp)
        # else: a forward is already in progress on this call stack (we ARE
        # the hub receiving that forwarded op) — apply locally below.

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
        if new_state.title is not None or "title" in doc:
            doc["title"] = new_state.title
        segments = doc.get("segments") or []
        for idx_str, text in new_state.segment_texts.items():
            i = int(idx_str)
            if 0 <= i < len(segments) and segments[i].get("text") != text:
                segments[i]["text"] = text
        _atomic_write_json(p, doc)
        _rewrite_txt_sidecar(p, doc)

    # speaker_labels participate in FTS, so reindex.
    db.upsert_path(p)

    return PatchResult(
        applied=asdict(applied_op),
        speakers=dict(new_state.speakers),
        _clocks={k: asdict(c) for k, c in new_state.clocks.items()},
        _history=[asdict(op) for op in new_state.history],
        lamport_assigned=new_lamport,
    )
