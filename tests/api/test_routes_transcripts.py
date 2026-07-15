import base64
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app
from tests.api._signing import signed_headers


# ── Signed-request helpers (block 5c) ──────────────────────────────────────
#
# PATCH /transcripts/{tid} requires a paired device signature. These
# helpers handle the pair + sign dance so each test stays concise. They
# also let us exercise the auth path realistically — no
# "auth_required=False" bypass — which is what production sees.


def _pair_device(client: TestClient, name: str = "test-device"):
    """Pair a fresh device. Returns (signing_key, device_id)."""
    from nacl.signing import SigningKey

    token = client.post("/pair/tokens").json()["token"]
    sk = SigningKey.generate()
    r = client.post(
        "/pair",
        json={
            "token": token,
            "device_pubkey_b64": base64.b64encode(
                bytes(sk.verify_key)
            ).decode("ascii"),
            "device_name": name,
        },
    )
    assert r.status_code == 200, r.text
    return sk, r.json()["device_id"]


def _signed_patch(
    client: TestClient, sk, device_id: str, path: str, body: dict
):
    """PATCH ``path`` with a body signed by ``sk`` as ``device_id``.

    Bypasses TestClient's json= serialization quirks by sending the
    body as raw bytes (``content=``) so the signed bytes are exactly
    the bytes the server reads back via ``await request.body()``.
    """
    body_bytes = json.dumps(body).encode("utf-8")
    return client.patch(
        path,
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            **signed_headers(sk, device_id, "PATCH", path, body_bytes),
        },
    )


@pytest.fixture
def app_with_lib(tmp_path):
    app = create_app(library_db_path=tmp_path / "library.db")
    app.state.library_dirs.add(tmp_path)
    sample = {
        "version": 1,
        "audio_path": str(tmp_path / "meet.mp3"),
        "duration_seconds": 60.0,
        "language": "en",
        "speakers": {"SPEAKER_00": "Alice"},
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": "hi"}],
        "models": {"asr": "faster-whisper:tiny"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (tmp_path / "meet.json").write_text(json.dumps(sample))
    return app


def test_list_transcripts_returns_metadata(app_with_lib):
    client = TestClient(app_with_lib)
    r = client.get("/transcripts")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    item = items[0]
    assert item["id"] == "meet"
    assert item["duration_seconds"] == 60.0
    assert item["speakers"] == 1


def test_get_transcript_returns_full_json(app_with_lib):
    client = TestClient(app_with_lib)
    r = client.get("/transcripts/meet")
    assert r.status_code == 200
    assert r.json()["segments"][0]["text"] == "hi"


# ── Library-dir snapshot race (concurrent .add() vs live iteration) ────────
#
# app.state.library_dirs is a plain set mutated off-thread by _on_complete_dir
# (and hub-client sync) while request handlers iterate it. A concurrent .add()
# growing the set mid-iteration raises "Set changed size during iteration".
# The fix: handlers pass a snapshot — set(...) is an atomic C-level copy — so
# reconcile / find_sidecar iterate a private copy. These tests pin that the
# handlers hand off a distinct object, not the live set.


def test_list_transcripts_passes_dir_snapshot(app_with_lib):
    captured = {}
    orig = app_with_lib.state.library_reconciler.reconcile

    def spy(dirs):
        captured["arg"] = dirs
        captured["is_live"] = dirs is app_with_lib.state.library_dirs
        return orig(dirs)

    # Instance attribute shadows the bound method for the duration of the test.
    app_with_lib.state.library_reconciler.reconcile = spy
    client = TestClient(app_with_lib)
    assert client.get("/transcripts").status_code == 200

    assert isinstance(captured["arg"], set)
    assert captured["is_live"] is False  # must be a snapshot, not the live set


def test_get_transcript_passes_dir_snapshot(app_with_lib, monkeypatch):
    import speechtotext.api.routes_transcripts as rt

    captured = {}
    orig = rt.find_sidecar

    def spy(dirs, tid):
        captured["is_live"] = dirs is app_with_lib.state.library_dirs
        captured["is_set"] = isinstance(dirs, set)
        return orig(dirs, tid)

    monkeypatch.setattr(rt, "find_sidecar", spy)
    client = TestClient(app_with_lib)
    assert client.get("/transcripts/meet").status_code == 200
    assert captured["is_set"] is True
    assert captured["is_live"] is False


def test_list_survives_concurrent_dir_adds(app_with_lib):
    # Reproduces the race: hammer GET /transcripts while a daemon thread adds
    # dirs to the live set. Without the snapshot this raises RuntimeError
    # ("Set changed size during iteration") → 500. With it, always 200.
    import threading

    client = TestClient(app_with_lib)
    stop = threading.Event()
    sentinel = Path("/nonexistent/churn-sentinel")

    def churn():
        # Oscillate the set's size so an iterator can observe a size change
        # mid-loop (the RuntimeError trigger) without letting the set grow
        # unbounded — mirrors the real writer, which mostly re-adds a dir.
        s = app_with_lib.state.library_dirs
        while not stop.is_set():
            s.add(sentinel)
            s.discard(sentinel)

    writer = threading.Thread(target=churn, daemon=True)
    writer.start()
    try:
        for _ in range(200):
            assert client.get("/transcripts").status_code == 200
    finally:
        stop.set()
        writer.join(timeout=1.0)


def test_patch_relabel_rewrites_sidecar(app_with_lib, tmp_path):
    client = TestClient(app_with_lib)
    r = client.patch("/transcripts/meet/relabel", json={"SPEAKER_00": "Bob"})
    assert r.status_code == 200
    raw = json.loads((tmp_path / "meet.json").read_text())
    assert raw["speakers"]["SPEAKER_00"] == "Bob"


def test_transcript_locks_are_weakly_held(app_with_lib):
    # One lock per transcript id, held forever, is a slow leak on a
    # long-running desktop app. Once no request holds a transcript's lock
    # it should be garbage-collected out of the registry.
    import gc

    from speechtotext.api.routes_transcripts import _get_transcript_lock

    lock = _get_transcript_lock(app_with_lib.state, "tid-1")
    assert app_with_lib.state.transcript_locks.get("tid-1") is lock
    del lock
    gc.collect()
    assert app_with_lib.state.transcript_locks.get("tid-1") is None


def test_relabel_takes_transcript_lock(app_with_lib, monkeypatch):
    # Bulk relabel does a read-modify-write on the same sidecar file as
    # the CRDT PATCH op. It must take the same per-transcript lock so a
    # concurrent CRDT write can't be clobbered (and vice versa).
    import speechtotext.api.routes_transcripts as rt

    seen: list[str] = []
    real = rt._get_transcript_lock

    def spy(state, tid):
        seen.append(tid)
        return real(state, tid)

    monkeypatch.setattr(rt, "_get_transcript_lock", spy)
    client = TestClient(app_with_lib)
    r = client.patch("/transcripts/meet/relabel", json={"SPEAKER_00": "Bob"})
    assert r.status_code == 200, r.text
    assert "meet" in seen


# ── PATCH /transcripts/{tid} (CRDT op) ─────────────────────────────────────


class TestPatchTranscriptOp:
    """Happy-path PATCH coverage. Each test pairs a device first."""

    def _op(self, op="relabel", key="speakers.SPEAKER_00", value="Bob",
            lamport_observed=0):
        return {
            "op": op,
            "key": key,
            "value": value,
            "lamport_observed": lamport_observed,
        }

    def test_applies_relabel(self, app_with_lib, tmp_path):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        r = _signed_patch(client, sk, dev_id, "/transcripts/meet", self._op())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["speakers"]["SPEAKER_00"] == "Bob"
        assert body["lamport_assigned"] >= 1
        raw = json.loads((tmp_path / "meet.json").read_text())
        assert raw["speakers"]["SPEAKER_00"] == "Bob"
        assert raw["_clocks"]["speakers.SPEAKER_00"]["device"] == dev_id

    def test_history_grows_on_each_op(self, app_with_lib, tmp_path):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        _signed_patch(
            client, sk, dev_id, "/transcripts/meet", self._op(value="Bob")
        )
        _signed_patch(
            client, sk, dev_id, "/transcripts/meet",
            self._op(value="Carol", lamport_observed=1),
        )
        raw = json.loads((tmp_path / "meet.json").read_text())
        assert len(raw["_history"]) == 2
        assert raw["speakers"]["SPEAKER_00"] == "Carol"

    def test_lamport_strictly_advances(self, app_with_lib):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        r1 = _signed_patch(
            client, sk, dev_id, "/transcripts/meet", self._op(value="V1")
        )
        r2 = _signed_patch(
            client, sk, dev_id, "/transcripts/meet",
            self._op(value="V2", lamport_observed=0),
        )
        assert r2.json()["lamport_assigned"] > r1.json()["lamport_assigned"]

    def test_lww_latest_lamport_wins(self, app_with_lib, tmp_path):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        for v, lobs in [("V1", 0), ("V2", 1), ("V3", 2), ("V_late", 0)]:
            _signed_patch(
                client, sk, dev_id, "/transcripts/meet",
                self._op(value=v, lamport_observed=lobs),
            )
        raw = json.loads((tmp_path / "meet.json").read_text())
        # Hub assigns sequential lamports; the latest call wins.
        assert raw["speakers"]["SPEAKER_00"] == "V_late"
        assert len(raw["_history"]) == 4

    def test_missing_transcript_returns_404(self, app_with_lib):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        r = _signed_patch(
            client, sk, dev_id, "/transcripts/does-not-exist", self._op()
        )
        assert r.status_code == 404

    def test_bad_op_type_returns_400(self, app_with_lib):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        r = _signed_patch(
            client, sk, dev_id, "/transcripts/meet", self._op(op="delete")
        )
        assert r.status_code == 400

    def test_bad_key_returns_400(self, app_with_lib):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        r = _signed_patch(
            client, sk, dev_id, "/transcripts/meet",
            self._op(key="transcript.title"),
        )
        assert r.status_code == 400

    def test_extra_body_device_field_silently_ignored(self, app_with_lib):
        """Server stamps verified device_id; client cannot inject one.

        Older clients still sending body.device must not be rejected —
        the field is accepted-and-ignored.
        """
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        body = self._op()
        body["device"] = ""
        r = _signed_patch(client, sk, dev_id, "/transcripts/meet", body)
        assert r.status_code == 200, r.text
        assert r.json()["applied"]["device"] == dev_id

    def test_negative_lamport_rejected(self, app_with_lib):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        body = self._op()
        body["lamport_observed"] = -1
        r = _signed_patch(client, sk, dev_id, "/transcripts/meet", body)
        assert r.status_code == 422

    def test_workspace_id_stamped_on_v1_doc(self, app_with_lib, tmp_path):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        raw_before = json.loads((tmp_path / "meet.json").read_text())
        assert "_workspace_id" not in raw_before
        _signed_patch(client, sk, dev_id, "/transcripts/meet", self._op())
        raw_after = json.loads((tmp_path / "meet.json").read_text())
        assert raw_after["_workspace_id"].startswith("ws_")

    def test_response_shape(self, app_with_lib):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        r = _signed_patch(
            client, sk, dev_id, "/transcripts/meet", self._op()
        )
        assert r.status_code == 200
        body = r.json()
        for key in ("applied", "speakers", "_clocks", "_history", "lamport_assigned"):
            assert key in body
        applied = body["applied"]
        for key in ("op", "key", "value", "device", "lamport", "ts"):
            assert key in applied
        assert applied["op"] == "relabel"
        assert applied["device"] == dev_id
        assert applied["from_value"] == "Alice"

    def test_forged_body_device_uses_verified_id(self, app_with_lib, tmp_path):
        """Regression: client-supplied body.device must be ignored.

        Attacker could otherwise forge a device_id and win LWW ties via
        string ordering, or attribute edits to other devices.
        """
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        body = self._op()
        body["device"] = "zzz-attacker"  # lex > any dev-<hex>
        r = _signed_patch(client, sk, dev_id, "/transcripts/meet", body)
        assert r.status_code == 200, r.text
        assert r.json()["applied"]["device"] == dev_id
        raw = json.loads((tmp_path / "meet.json").read_text())
        assert raw["_clocks"]["speakers.SPEAKER_00"]["device"] == dev_id

    def test_concurrent_patches_dont_clobber(
        self, app_with_lib, tmp_path, monkeypatch
    ):
        """Two PATCHes on the same transcript must both land in history.

        Without a per-transcript lock the read-modify-write sequence
        races: both requests read the same on-disk state, merge, then
        the second write clobbers the first. The lock serialises them.
        """
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor

        import speechtotext.api.routes_transcripts as routes_t

        # Slow down the write phase so the two requests' reads
        # interleave (without delay the OS would likely serialise
        # them). With the lock the second request waits at the lock
        # and re-reads after the first writes. Without the lock both
        # see the same state and the second clobbers.
        real_dumps = routes_t.json.dumps

        def slow_dumps(*args, **kwargs):
            time.sleep(0.05)
            return real_dumps(*args, **kwargs)

        monkeypatch.setattr(routes_t.json, "dumps", slow_dumps)

        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)

        def do_patch(value: str):
            return _signed_patch(
                client,
                sk,
                dev_id,
                "/transcripts/meet",
                {
                    "op": "relabel",
                    "key": "speakers.SPEAKER_00",
                    "value": value,
                    "lamport_observed": 0,
                },
            )

        ready = threading.Event()

        def run(value: str):
            ready.wait(timeout=2.0)
            return do_patch(value)

        with ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(run, "Bob")
            f2 = ex.submit(run, "Carol")
            ready.set()
            r1 = f1.result(timeout=10)
            r2 = f2.result(timeout=10)

        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text

        raw = json.loads((tmp_path / "meet.json").read_text())
        assert len(raw["_history"]) == 2, (
            f"expected both ops in history, lock missing? got {raw['_history']}"
        )


def test_patch_transcript_op_accepts_admin_bearer(app_with_lib, monkeypatch):
    monkeypatch.setenv("LOCALLEXIS_API_TOKEN", "secret")
    client = TestClient(app_with_lib)
    body = json.dumps(
        {"op": "relabel", "key": "speakers.SPEAKER_00", "value": "Alice",
         "lamport_observed": 0}
    ).encode("utf-8")
    r = client.patch(
        "/transcripts/meet",
        content=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer secret"},
    )
    assert r.status_code == 200, r.text
    assert "lamport_assigned" in r.json()


# ── PATCH auth (block 5c) ──────────────────────────────────────────────────


class TestPatchTranscriptOpAuth:
    """Signed-request middleware behaviour on PATCH /transcripts/{tid}."""

    def _body(self) -> dict:
        return {
            "op": "relabel",
            "key": "speakers.SPEAKER_00",
            "value": "X",
            "lamport_observed": 0,
        }

    def test_no_headers_returns_401(self, app_with_lib):
        client = TestClient(app_with_lib)
        r = client.patch("/transcripts/meet", json=self._body())
        assert r.status_code == 401
        assert "X-Device-Id" in r.text or "X-Signature-B64" in r.text

    def test_unknown_device_returns_401(self, app_with_lib):
        from nacl.signing import SigningKey

        client = TestClient(app_with_lib)
        sk = SigningKey.generate()
        body_bytes = json.dumps(self._body()).encode("utf-8")
        r = client.patch(
            "/transcripts/meet",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                **signed_headers(sk, "dev-unknown000", "PATCH", "/transcripts/meet", body_bytes),
            },
        )
        assert r.status_code == 401
        assert "unknown device" in r.text

    def test_wrong_signing_key_returns_401(self, app_with_lib):
        from nacl.signing import SigningKey

        client = TestClient(app_with_lib)
        _, dev_id = _pair_device(client)
        wrong_sk = SigningKey.generate()
        body_bytes = json.dumps(self._body()).encode("utf-8")
        r = client.patch(
            "/transcripts/meet",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                **signed_headers(wrong_sk, dev_id, "PATCH", "/transcripts/meet", body_bytes),
            },
        )
        assert r.status_code == 401

    def test_tampered_body_returns_401(self, app_with_lib):
        """Signing the right bytes but sending different bytes → 401."""
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        signed_body = json.dumps(self._body()).encode("utf-8")
        tampered_body = json.dumps({**self._body(), "value": "TAMPERED"}).encode("utf-8")
        # Sign the original body but send the tampered one → must not verify.
        r = client.patch(
            "/transcripts/meet",
            content=tampered_body,
            headers={
                "Content-Type": "application/json",
                **signed_headers(sk, dev_id, "PATCH", "/transcripts/meet", signed_body),
            },
        )
        assert r.status_code == 401

    def test_bad_signature_encoding_returns_401(self, app_with_lib):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        body_bytes = json.dumps(self._body()).encode()
        headers = {
            "Content-Type": "application/json",
            **signed_headers(sk, dev_id, "PATCH", "/transcripts/meet", body_bytes),
        }
        headers["X-Signature-B64"] = "$$$ not base64 $$$"
        r = client.patch("/transcripts/meet", content=body_bytes, headers=headers)
        assert r.status_code == 401

    def test_successful_call_updates_last_seen(self, app_with_lib):
        client = TestClient(app_with_lib)
        sk, dev_id = _pair_device(client)
        before = app_with_lib.state.device_registry.get(dev_id)
        assert before["last_seen"] is None
        _signed_patch(
            client, sk, dev_id, "/transcripts/meet", self._body()
        )
        after = app_with_lib.state.device_registry.get(dev_id)
        assert after["last_seen"] is not None


# ── search route params: fuzzy, sort (block 4) ──────────────────────────────


def test_search_returns_segment_hits(app_with_lib):
    client = TestClient(app_with_lib)
    r = client.get("/transcripts", params={"q": "hi"})
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["hits"][0]["segment_index"] == 0
    assert items[0]["total_hits"] == 1


def test_search_fuzzy_param(app_with_lib, tmp_path):
    # Add a transcript containing "Kaitlyn"; query the phonetic twin "Catelin".
    sample = {
        "version": 1,
        "audio_path": str(tmp_path / "kaitlyn.mp3"),
        "duration_seconds": 5.0,
        "language": "en",
        "speakers": {"SPEAKER_00": "Alice"},
        "segments": [{"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00",
                      "text": "then Kaitlyn presented"}],
        "models": {"asr": "faster-whisper:tiny"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (tmp_path / "kaitlyn.json").write_text(json.dumps(sample))
    client = TestClient(app_with_lib)
    exact = client.get("/transcripts", params={"q": "Catelin"}).json()
    assert exact == [] or not any(i.get("hits") for i in exact)
    fuzzy = client.get("/transcripts", params={"q": "Catelin", "fuzzy": 1}).json()
    assert len(fuzzy) == 1
    assert fuzzy[0]["id"] == "kaitlyn"
    assert fuzzy[0]["hits"][0]["segment_index"] == 0


def test_search_sort_param_validation(app_with_lib):
    client = TestClient(app_with_lib)
    assert client.get("/transcripts", params={"q": "hi", "sort": "date"}).status_code == 200
    assert client.get("/transcripts", params={"q": "hi", "sort": "bogus"}).status_code == 422
