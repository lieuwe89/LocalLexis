"""Tests for /sync/snapshot and /sync/since/{cursor}."""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from speechtotext.api.app import create_app
from tests.api._signing import signed_headers


def _make_doc(audio_path: Path, speakers: dict[str, str] | None = None) -> dict:
    return {
        "version": 2,
        "audio_path": str(audio_path),
        "duration_seconds": 5.0,
        "language": "en",
        "speakers": speakers or {"SPEAKER_00": "Alice"},
        "segments": [
            {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": "hi"}
        ],
        "models": {"asr": "faster-whisper:tiny"},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "_workspace_id": "ws_test",
        "_clocks": {},
        "_history": [],
    }


def _write_transcript(tmp_path: Path, name: str, doc: dict | None = None) -> Path:
    audio = tmp_path / f"{name}.mp3"
    audio.write_bytes(b"fake")
    json_path = audio.with_suffix(".json")
    json_path.write_text(json.dumps(doc or _make_doc(audio)))
    return json_path


@pytest.fixture
def app(tmp_path):
    app = create_app(library_db_path=tmp_path / "library.db")
    app.state.library_dirs.add(tmp_path)
    return app


def _pair(client: TestClient):
    token = client.post("/pair/tokens").json()["token"]
    sk = SigningKey.generate()
    r = client.post(
        "/pair",
        json={
            "token": token,
            "device_pubkey_b64": base64.b64encode(
                bytes(sk.verify_key)
            ).decode("ascii"),
            "device_name": "test-device",
        },
    )
    return sk, r.json()["device_id"]


def _signed_get(client, sk, device_id, path: str):
    return client.get(path, headers=signed_headers(sk, device_id, "GET", path))


# ── Snapshot ──────────────────────────────────────────────────────────────


class TestSyncSnapshot:
    def test_empty_library(self, app):
        client = TestClient(app)
        sk, dev_id = _pair(client)
        r = _signed_get(client, sk, dev_id, "/sync/snapshot")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["transcripts"] == []
        assert body["cursor"] == 0.0
        assert body["workspace_id"].startswith("ws_")

    def test_returns_all_transcripts(self, app, tmp_path):
        _write_transcript(tmp_path, "a")
        _write_transcript(tmp_path, "b")
        _write_transcript(tmp_path, "c")
        client = TestClient(app)
        sk, dev_id = _pair(client)
        r = _signed_get(client, sk, dev_id, "/sync/snapshot")
        body = r.json()
        ids = sorted(Path(d["audio_path"]).name for d in body["transcripts"])
        assert ids == ["a.mp3", "b.mp3", "c.mp3"]
        assert body["cursor"] > 0

    def test_response_shape(self, app, tmp_path):
        _write_transcript(tmp_path, "a")
        client = TestClient(app)
        sk, dev_id = _pair(client)
        r = _signed_get(client, sk, dev_id, "/sync/snapshot")
        body = r.json()
        assert set(body.keys()) == {"workspace_id", "cursor", "transcripts"}
        assert "speakers" in body["transcripts"][0]

    def test_snapshot_includes_transcript_id(self, app, tmp_path):
        # Wire contract: every transcript carries a stable `id` (the json
        # file stem) so mobile clients can key rows without inferring from
        # audio_path. Android SyncClient.parseTranscript hard-fails without it.
        _write_transcript(tmp_path, "alpha")
        client = TestClient(app)
        sk, dev_id = _pair(client)
        body = _signed_get(client, sk, dev_id, "/sync/snapshot").json()
        assert body["transcripts"][0]["id"] == "alpha"


    def test_skips_doc_with_segments_missing_wire_fields(self, app, tmp_path):
        # A doc whose segments lack start/end/text would make the Android
        # client reject the whole batch — the hub must drop just that one.
        _write_transcript(tmp_path, "good")
        bad = _make_doc(tmp_path / "bad.mp3")
        bad["segments"] = [{"speaker": "SPEAKER_00", "text": "hi"}]  # no start/end
        _write_transcript(tmp_path, "bad", doc=bad)
        client = TestClient(app)
        sk, dev_id = _pair(client)
        body = _signed_get(client, sk, dev_id, "/sync/snapshot").json()
        ids = {d["id"] for d in body["transcripts"]}
        assert ids == {"good"}  # "bad" dropped, "good" still delivered


# ── Since ─────────────────────────────────────────────────────────────────


class TestSyncSince:
    def test_returns_only_newer_transcripts(self, app, tmp_path):
        _write_transcript(tmp_path, "old")
        client = TestClient(app)
        sk, dev_id = _pair(client)
        # Take a snapshot to learn the current cursor.
        snap = _signed_get(client, sk, dev_id, "/sync/snapshot").json()
        cursor = snap["cursor"]
        # Add a new transcript whose mtime is strictly later.
        time.sleep(0.02)
        _write_transcript(tmp_path, "new")
        # /sync/since with the snapshot cursor should return only "new".
        r = _signed_get(client, sk, dev_id, f"/sync/since/{cursor}")
        body = r.json()
        names = [Path(d["audio_path"]).name for d in body["transcripts"]]
        assert names == ["new.mp3"]
        assert body["cursor"] > cursor

    def test_no_changes_advances_to_max_seen(self, app, tmp_path):
        _write_transcript(tmp_path, "a")
        client = TestClient(app)
        sk, dev_id = _pair(client)
        snap = _signed_get(client, sk, dev_id, "/sync/snapshot").json()
        cursor = snap["cursor"]
        # Poll again with that cursor — nothing has changed.
        r = _signed_get(client, sk, dev_id, f"/sync/since/{cursor}")
        body = r.json()
        assert body["transcripts"] == []
        # Cursor stays at the same point (no transcripts > cursor).
        assert body["cursor"] == cursor

    def test_cursor_zero_equivalent_to_snapshot(self, app, tmp_path):
        _write_transcript(tmp_path, "a")
        _write_transcript(tmp_path, "b")
        client = TestClient(app)
        sk, dev_id = _pair(client)
        snap = _signed_get(client, sk, dev_id, "/sync/snapshot").json()
        since_zero = _signed_get(client, sk, dev_id, "/sync/since/0").json()
        # Both return the same docs (order independent — compare as sets
        # via id field stand-in: the audio_path basename).
        snap_names = {
            Path(d["audio_path"]).name for d in snap["transcripts"]
        }
        since_names = {
            Path(d["audio_path"]).name for d in since_zero["transcripts"]
        }
        assert snap_names == since_names

    def test_picks_up_patched_transcript(self, app, tmp_path):
        """A PATCH to an existing transcript updates its mtime; the next
        /sync/since with the prior cursor must surface it."""
        _write_transcript(tmp_path, "a")
        client = TestClient(app)
        sk, dev_id = _pair(client)
        snap = _signed_get(client, sk, dev_id, "/sync/snapshot").json()
        cursor = snap["cursor"]
        # Wait so mtime tick is observable across filesystems.
        time.sleep(0.02)
        # Patch the speaker label.
        body = {
            "op": "relabel",
            "key": "speakers.SPEAKER_00",
            "value": "Renamed",
            "device": "test",
            "lamport_observed": 0,
        }
        body_bytes = json.dumps(body).encode()
        patch_r = client.patch(
            "/transcripts/a",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                **signed_headers(sk, dev_id, "PATCH", "/transcripts/a", body_bytes),
            },
        )
        assert patch_r.status_code == 200, patch_r.text
        # Now poll for changes since the original cursor.
        r = _signed_get(client, sk, dev_id, f"/sync/since/{cursor}")
        body = r.json()
        assert len(body["transcripts"]) == 1
        assert (
            body["transcripts"][0]["speakers"]["SPEAKER_00"] == "Renamed"
        )

    def test_unauthenticated_returns_401(self, app, tmp_path):
        _write_transcript(tmp_path, "a")
        client = TestClient(app)
        r = client.get("/sync/snapshot")
        assert r.status_code == 401
        r = client.get("/sync/since/0")
        assert r.status_code == 401


# ── Pagination ──────────────────────────────────────────────────────────────


class TestSyncPagination:
    def test_snapshot_limit_caps_results(self, app, tmp_path):
        for n in ("a", "b", "c"):
            _write_transcript(tmp_path, n)
            time.sleep(0.01)
        client = TestClient(app)
        sk, dev = _pair(client)
        r = _signed_get(client, sk, dev, "/sync/snapshot?limit=2")
        assert r.status_code == 200, r.text
        assert len(r.json()["transcripts"]) == 2

    def test_snapshot_offset_pages_through_all(self, app, tmp_path):
        for n in ("a", "b", "c"):
            _write_transcript(tmp_path, n)
            time.sleep(0.01)
        client = TestClient(app)
        sk, dev = _pair(client)
        p1 = _signed_get(client, sk, dev, "/sync/snapshot?limit=2&offset=0").json()
        p2 = _signed_get(client, sk, dev, "/sync/snapshot?limit=2&offset=2").json()
        n1 = {Path(d["audio_path"]).name for d in p1["transcripts"]}
        n2 = {Path(d["audio_path"]).name for d in p2["transcripts"]}
        assert len(p1["transcripts"]) == 2
        assert len(p2["transcripts"]) == 1
        assert n1.isdisjoint(n2)
        assert n1 | n2 == {"a.mp3", "b.mp3", "c.mp3"}

    def test_since_respects_limit(self, app, tmp_path):
        for n in ("a", "b", "c"):
            _write_transcript(tmp_path, n)
            time.sleep(0.01)
        client = TestClient(app)
        sk, dev = _pair(client)
        r = _signed_get(client, sk, dev, "/sync/since/0?limit=2")
        assert len(r.json()["transcripts"]) == 2
