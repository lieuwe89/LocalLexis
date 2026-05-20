"""SQLite-backed registry of paired devices.

A device row is created when ``POST /pair`` completes successfully.
From that point on, the hub uses the stored pubkey to verify the
device's signed requests (see :mod:`speechtotext.api.auth`). The
device's ``last_seen`` is updated on every successful verification —
useful operationally for "which devices are still active?"

Schema is intentionally tiny: device_id (hub-assigned), pubkey_b64
(device's Ed25519 verify key, base64), name (user-visible label),
paired_at, last_seen. No indices beyond the primary key; the table
stays small (handful of devices per workspace).
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_devices_db_path() -> Path:
    """Platform app-data path for the devices SQLite file."""
    from speechtotext.api.library_db import default_app_data_dir

    return default_app_data_dir() / "devices.db"


_DDL = """
CREATE TABLE IF NOT EXISTS devices (
    device_id   TEXT PRIMARY KEY,
    pubkey_b64  TEXT NOT NULL,
    name        TEXT NOT NULL,
    paired_at   TEXT NOT NULL,
    last_seen   TEXT
)
"""


class DeviceRegistry:
    """Thread-safe SQLite registry of paired devices."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.path = Path(db_path) if db_path else default_devices_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._lock, self._conn:
            self._conn.execute(_DDL)

    def register(self, device_id: str, pubkey_b64: str, name: str) -> None:
        """Insert (or replace) a device record.

        ``INSERT OR REPLACE`` because pairing the same device id again
        (manual reset on the device side) should be a no-fuss rotate.
        """
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO devices
                  (device_id, pubkey_b64, name, paired_at, last_seen)
                VALUES (?, ?, ?, ?, ?)
                """,
                (device_id, pubkey_b64, name, _now_iso(), None),
            )

    def get(self, device_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM devices WHERE device_id=?", (device_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_all(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM devices ORDER BY paired_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_last_seen(self, device_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE devices SET last_seen=? WHERE device_id=?",
                (_now_iso(), device_id),
            )

    def delete(self, device_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM devices WHERE device_id=?", (device_id,)
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
