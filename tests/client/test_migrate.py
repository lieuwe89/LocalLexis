"""Unit tests for speechtotext.client.migrate.sweep_local: row filtering and
the record-and-continue vs transport-error-stops distinction. migrate_one
itself is exercised end-to-end in tests/api/test_migrate_e2e.py (it needs a
real hub loopback + LibraryDB), so here migrate_one is monkeypatched and a
minimal fake db stands in for LibraryDB.list()."""
import json
from pathlib import Path

import httpx

from speechtotext.client import migrate


class FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def list(self, limit=10000):
        return self._rows


def _rows(*ids):
    return [{"id": t, "path": f"/x/{t}.json", "origin": "local"} for t in ids]


def _patch_migrate_one(monkeypatch, fail_on: dict):
    """fail_on maps json filename -> exception to raise. Returns call list."""
    calls: list[Path] = []

    def fake_migrate_one(client, db_arg, json_path):
        calls.append(json_path)
        exc = fail_on.get(json_path.name)
        if exc is not None:
            raise exc
        return "migrated"

    monkeypatch.setattr(migrate, "migrate_one", fake_migrate_one)
    return calls


def test_sweep_local_continues_on_verify_error(monkeypatch):
    calls = _patch_migrate_one(monkeypatch, {
        "t2.json": migrate.MigrateError("t2: segments mismatch after sync"),
    })
    report = migrate.sweep_local(None, FakeDB(_rows("t1", "t2", "t3")))
    assert report == {
        "migrated": ["t1", "t3"],
        "failed": [{"id": "t2", "error": "t2: segments mismatch after sync"}],
    }
    assert len(calls) == 3  # a verify failure doesn't stop the sweep


def test_sweep_local_stops_on_transport_error(monkeypatch):
    calls = _patch_migrate_one(monkeypatch, {
        "t2.json": httpx.ConnectError("hub unreachable"),
    })
    report = migrate.sweep_local(None, FakeDB(_rows("t1", "t2", "t3")))
    assert report == {
        "migrated": ["t1"],
        "failed": [{"id": "t2", "error": "ConnectError: hub unreachable"}],
    }
    assert len(calls) == 2  # t3 never attempted: hub gone, retry next run


def test_sweep_local_continues_on_bad_row_errors(monkeypatch):
    """Corrupt local JSON or a hub 4xx is that row's problem, not the
    sweep's — no head-of-line blocking."""
    calls = _patch_migrate_one(monkeypatch, {
        "t1.json": json.JSONDecodeError("bad", "{", 0),
        "t2.json": httpx.HTTPStatusError("400", request=None, response=None),
    })
    report = migrate.sweep_local(None, FakeDB(_rows("t1", "t2", "t3")))
    assert report["migrated"] == ["t3"]
    assert [f["id"] for f in report["failed"]] == ["t1", "t2"]
    assert len(calls) == 3


def test_sweep_local_skips_hub_origin_and_error_rows(monkeypatch):
    calls = _patch_migrate_one(monkeypatch, {})
    rows = [
        {"id": "a", "path": "/x/a.json", "origin": "local"},
        {"id": "b", "path": "/x/b.json", "origin": "hub"},
        {"id": "c", "path": "/x/c.json", "origin": "local", "error": "parse"},
    ]
    report = migrate.sweep_local(None, FakeDB(rows))
    assert report == {"migrated": ["a"], "failed": []}
    assert calls == [Path("/x/a.json")]
