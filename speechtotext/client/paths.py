"""Filesystem layout for the hub client. Everything lives under
``<app-data>/hub/``. Re-exports default_app_data_dir so tests can patch
one module-local binding (same pattern as tests/api/conftest.py)."""

from __future__ import annotations

from pathlib import Path

from speechtotext.api.library_db import default_app_data_dir

__all__ = ["default_app_data_dir", "hub_dir", "outbox_dir", "synced_dir"]


def hub_dir() -> Path:
    return default_app_data_dir() / "hub"


def outbox_dir() -> Path:
    return hub_dir() / "outbox"


def synced_dir() -> Path:
    return hub_dir() / "synced"
