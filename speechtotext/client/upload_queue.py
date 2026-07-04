"""Disk-backed upload outbox.

Layout per entry (timestamp-prefixed so lexical order == FIFO):

    outbox/<stamp>-<rand>-<name>.wav            # the audio
    outbox/<stamp>-<rand>-<name>.wav.meta.json  # {"job_id": ...}

`sweep()` uploads oldest-first and deletes entries on 2xx. The first
failure aborts the batch: one unreachable hub shouldn't spin through N
files' worth of timeouts. The caller's retry loop (the hub runtime)
calls sweep again after a backoff.
"""

from __future__ import annotations

import json
import secrets
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from speechtotext.client.paths import outbox_dir

_META_SUFFIX = ".meta.json"


@dataclass(frozen=True)
class OutboxEntry:
    audio_path: Path
    meta_path: Path
    job_id: str | None


def enqueue(audio_path: Path, *, job_id: str | None = None) -> OutboxEntry:
    root = outbox_dir()
    root.mkdir(parents=True, exist_ok=True)
    # Use time.time() for monotonically increasing ordering (sub-second precision)
    # Format: YYYYMMdd-HHMMSS-microseconds
    now = time.time()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now))
    micros = int((now % 1.0) * 1_000_000)
    dest = root / f"{stamp}-{micros:06d}-{secrets.token_hex(4)}-{audio_path.name}"
    shutil.copy2(audio_path, dest)
    meta_path = Path(str(dest) + _META_SUFFIX)
    meta_path.write_text(json.dumps({"job_id": job_id}), encoding="utf-8")
    return OutboxEntry(audio_path=dest, meta_path=meta_path, job_id=job_id)


def pending() -> list[OutboxEntry]:
    root = outbox_dir()
    if not root.exists():
        return []
    entries: list[OutboxEntry] = []
    for meta_path in sorted(root.glob(f"*{_META_SUFFIX}")):
        audio_path = Path(str(meta_path)[: -len(_META_SUFFIX)])
        if not audio_path.exists():
            meta_path.unlink(missing_ok=True)  # orphan meta
            continue
        try:
            job_id = json.loads(meta_path.read_text()).get("job_id")
        except (OSError, json.JSONDecodeError):
            job_id = None
        entries.append(OutboxEntry(audio_path, meta_path, job_id))
    return entries


def sweep(hub_client) -> list[OutboxEntry]:
    """Upload all pending entries oldest-first. Returns entries that were
    uploaded. Stops at the first failure (hub presumed unreachable)."""
    done: list[OutboxEntry] = []
    for entry in pending():
        try:
            hub_client.upload_audio(entry.audio_path)
        except Exception:
            break
        entry.audio_path.unlink(missing_ok=True)
        entry.meta_path.unlink(missing_ok=True)
        done.append(entry)
    return done
