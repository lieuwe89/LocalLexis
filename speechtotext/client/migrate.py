"""One-transcript migration to the hub: push, pull back, verify, archive.

The invariant this module exists to protect: a local original is NEVER
trashed before its hub copy has synced back down and been verified.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import httpx

from speechtotext.api.trash import trash_transcript
from speechtotext.client import sync_puller
from speechtotext.client.paths import synced_dir

_log = logging.getLogger(__name__)

# Serializes concurrent sweeps: the manual migrate-library endpoint and the
# HubRuntime post-migration auto-sweep can race over the same local rows —
# the loser's trash_transcript hits FileNotFoundError, which shows up as a
# false "failed" in the report and wrongly blocks migrated_at. With the
# lock the second caller re-lists and finds nothing left to do.
_sweep_lock = threading.Lock()


class MigrateError(RuntimeError):
    pass


def migrate_one(client, db, json_path: Path) -> str:
    """Migrate one local transcript. Returns "migrated". Raises MigrateError
    if the hub copy cannot be verified; the original is left untouched then."""
    doc = json.loads(json_path.read_text(encoding="utf-8"))
    tid = json_path.stem
    audio_raw = doc.get("audio_path")
    audio = Path(audio_raw) if audio_raw else None

    client.import_transcript(json_path, audio)  # "exists" answer is fine: resume
    sync_puller.pull_once(client)

    synced = synced_dir() / f"{tid}.json"
    if not synced.is_file():
        raise MigrateError(f"{tid}: hub copy did not sync back")
    # Content equality, not just counts: an earlier interrupted run may have
    # pushed an older version ("exists" on re-push), after which local edits
    # never reach the hub — a count-only check would archive the edited
    # original and crown the stale hub copy SSOT. The hub stores the doc
    # as-is minus audio_path, so exact equality is the right bar.
    sdoc = json.loads(synced.read_text(encoding="utf-8"))
    for field in ("segments", "speakers", "title"):
        if sdoc.get(field) != doc.get(field):
            raise MigrateError(f"{tid}: {field} mismatch after sync")

    # Index the synced copy BEFORE removing the original so the library
    # never shows a gap, then archive the original files to trash.
    db.upsert_path(synced)
    try:
        trash_transcript(json_path)
    except OSError as exc:
        # Verified hub copy is live and indexed; the bytes are safe. But the
        # DB row now points at the synced copy, so the original is invisible
        # to UI and sweep — shout so someone cleans it up by hand.
        _log.error(
            "migrated %s but archiving the original failed — orphaned "
            "files at %s: %s", tid, json_path, exc,
        )
    # No-op safety net: upsert_path already re-pointed the row (same tid,
    # ON CONFLICT(id) DO UPDATE), so no row matches the original path.
    db.delete_by_path(json_path)
    return "migrated"


def sweep_local(client, db, *, limit: int = 10000) -> dict:
    """Migrate every indexed local-origin transcript. Used by the one-time
    migration job AND (post-migration) the runtime auto-sweep. Stops early
    on the first network-level failure; per-transcript failures (verify,
    corrupt JSON, hub 4xx) are recorded and skipped."""
    # Post-migration the runtime calls this every cycle; the count keeps
    # the steady state (no local rows left) essentially free.
    if db.count_local_origin() == 0:
        return {"migrated": [], "failed": []}
    with _sweep_lock:
        migrated: list[str] = []
        failed: list[dict] = []
        # ponytail: no pagination; a page == limit means rows beyond it were
        # never seen this run — log it, paginate if libraries ever grow past 10k.
        rows = db.list(limit=limit)
        if len(rows) == limit:
            _log.warning("sweep_local: row count hit limit=%d; some rows unseen", limit)
        for row in rows:
            if row.get("origin") != "local" or row.get("error"):
                continue
            json_path = Path(row["path"])
            try:
                migrate_one(client, db, json_path)
                migrated.append(row["id"])
            except MigrateError as exc:
                failed.append({"id": row["id"], "error": str(exc)})
            except httpx.TransportError as exc:  # hub unreachable; stop, retry next run
                failed.append({"id": row["id"], "error": f"{type(exc).__name__}: {exc}"})
                break
            except Exception as exc:  # this row is bad (corrupt JSON/hub 4xx); next may be fine
                failed.append({"id": row["id"], "error": f"{type(exc).__name__}: {exc}"})
        if failed:
            _log.warning(
                "sweep_local: %d transcript(s) failed to migrate: %s",
                len(failed), ", ".join(f["id"] for f in failed),
            )
        return {"migrated": migrated, "failed": failed}
