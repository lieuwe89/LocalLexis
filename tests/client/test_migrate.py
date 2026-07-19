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
        return list(self._rows)

    def count_local_origin(self):
        return sum(
            1 for r in self._rows
            if r.get("origin") == "local" and not r.get("error")
        )


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


def test_sweep_local_logs_failures(monkeypatch, caplog):
    """The runtime auto-sweep discards the report, so this log line is the
    only visibility into repeat per-row failures."""
    _patch_migrate_one(monkeypatch, {
        "t2.json": migrate.MigrateError("t2: segments mismatch after sync"),
    })
    with caplog.at_level("WARNING", logger="speechtotext.client.migrate"):
        migrate.sweep_local(None, FakeDB(_rows("t1", "t2", "t3")))
    assert any("t2" in rec.message for rec in caplog.records)


def test_sweep_local_short_circuits_when_no_local_rows(monkeypatch):
    calls = _patch_migrate_one(monkeypatch, {})
    db = FakeDB([{"id": "b", "path": "/x/b.json", "origin": "hub"}])
    report = migrate.sweep_local(None, db)
    assert report == {"migrated": [], "failed": []}
    assert calls == []


def test_sweep_local_serializes_concurrent_sweeps(monkeypatch):
    """The manual migrate job and the runtime auto-sweep may run at the
    same time. Without _sweep_lock both would list the same local rows and
    the loser's trash_transcript would blow up into a false failure; with
    it the second sweep sees an empty (post-migration) library."""
    import threading
    import time

    db = FakeDB(_rows("t1", "t2", "t3"))

    def fake_migrate_one(client, db_arg, json_path):
        time.sleep(0.02)  # widen the race window
        db_arg._rows = [r for r in db_arg._rows if r["path"] != str(json_path)]
        return "migrated"

    monkeypatch.setattr(migrate, "migrate_one", fake_migrate_one)

    reports = []

    def run():
        reports.append(migrate.sweep_local(None, db))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    all_migrated = [tid for rep in reports for tid in rep["migrated"]]
    assert sorted(all_migrated) == ["t1", "t2", "t3"]  # each row exactly once
    assert all(rep["failed"] == [] for rep in reports)
