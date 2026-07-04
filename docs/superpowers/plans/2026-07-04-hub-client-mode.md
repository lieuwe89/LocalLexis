# Desktop Hub Client Mode Implementation Plan (Spec Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the desktop app join a remote headless hub: pair via pasted string, upload all captured audio to the hub for transcription, and pull the hub's transcripts into the local searchable library.

**Architecture:** New `speechtotext/client/` package (mirror of the server-side `api/` package): device identity + Ed25519 request signing (reusing `speechtotext.api.auth.build_signed_message` as the single canonical message builder), a disk-backed upload outbox with a retry loop, and a background sync puller that writes hub transcripts into a local dir indexed by the existing `LibraryDB`. The sidecar exposes loopback `/client/hub/*` routes for the Tauri UI; when joined, `POST /jobs/transcribe` enqueues to the outbox instead of running the local pipeline. A `locallexis-hub pair` CLI subcommand mints pairing payloads on headless hubs.

**Tech Stack:** Python 3.11+, PyNaCl (Ed25519/SealedBox), httpx, FastAPI, pytest; TypeScript/React (Tauri UI), vitest.

**Spec:** `docs/superpowers/specs/2026-07-04-hub-client-web-ui-design.md`

**Conventions that bind every task:**
- Run Python tests with `.venv/bin/python -m pytest` (bare `pytest` uses system python3.14 which segfaults importing ctranslate2 — see DEVLOG 2026-06-30).
- `tests/api/conftest.py` has an autouse fixture isolating app-data; add the same isolation for `speechtotext.client` paths in `tests/client/conftest.py` (Task 1).
- The signature wire scheme is v2: `locallexis-sig-v2\nMETHOD\nPATH[?QUERY]\nTIMESTAMP\nNONCE\nsha256(body)` signed with the device Ed25519 key, carried in `X-Device-Id`, `X-Signature-B64`, `X-Timestamp`, `X-Nonce` headers (`speechtotext/api/auth.py:70`).
- Version bump + commit convention: `feat:`/`test:` prefixes, no DEVLOG.md staging ever.

---

### Task 1: Client package skeleton + test isolation

**Files:**
- Create: `speechtotext/client/__init__.py`
- Create: `tests/client/__init__.py`
- Create: `tests/client/conftest.py`

- [ ] **Step 1: Create empty package inits**

`speechtotext/client/__init__.py`:
```python
"""Hub-client package — the desktop sidecar's client side of hub mode.

Server counterpart lives in :mod:`speechtotext.api`. This package holds
device identity, request signing, the upload outbox, and the sync puller.
"""
```

`tests/client/__init__.py`: empty file.

- [ ] **Step 2: Write the conftest**

`tests/client/conftest.py`:
```python
import pytest


@pytest.fixture(autouse=True)
def _isolated_client_data(tmp_path_factory, monkeypatch):
    """Point the client package's app-data lookups at a temp dir so tests
    never touch the developer's real ~/Library/.../locallexis/hub."""
    import speechtotext.client.paths as _paths

    data_dir = tmp_path_factory.mktemp("clientdata")
    monkeypatch.setattr(_paths, "default_app_data_dir", lambda: data_dir)
```

- [ ] **Step 3: Create `speechtotext/client/paths.py`** (conftest imports it)

```python
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
```

- [ ] **Step 4: Sanity-run the empty suite**

Run: `.venv/bin/python -m pytest tests/client -v`
Expected: `no tests ran` (collection succeeds, no import errors)

- [ ] **Step 5: Commit**

```bash
git add speechtotext/client tests/client
git commit -m "feat(client): hub-client package skeleton with isolated test app-data"
```

---

### Task 2: Device identity (`identity.py`)

**Files:**
- Create: `speechtotext/client/identity.py`
- Test: `tests/client/test_identity.py`

- [ ] **Step 1: Write failing tests**

`tests/client/test_identity.py`:
```python
import base64
import os
import stat

from nacl.public import SealedBox
from nacl.signing import SigningKey

from speechtotext.client import identity
from speechtotext.client.paths import hub_dir


def test_generate_creates_key_file_with_0600():
    ident = identity.generate()
    key_file = hub_dir() / "device_key.json"
    assert key_file.exists()
    mode = stat.S_IMODE(os.stat(key_file).st_mode)
    assert mode == 0o600
    assert len(ident.verify_key_b64()) > 0


def test_load_roundtrips_generated_identity():
    ident = identity.generate()
    loaded = identity.load()
    assert loaded is not None
    assert loaded.verify_key_b64() == ident.verify_key_b64()


def test_load_returns_none_when_absent():
    assert identity.load() is None


def test_unseal_workspace_key():
    ident = identity.generate()
    workspace_key = os.urandom(32)
    curve_pub = SigningKey(
        base64.b64decode(ident._signing_key_b64)
    ).verify_key.to_curve25519_public_key()
    sealed = SealedBox(curve_pub).encrypt(workspace_key)
    assert ident.unseal(sealed) == workspace_key


def test_store_and_read_workspace_key():
    ident = identity.generate()
    ident.store_workspace_key(b"\x01" * 32)
    assert identity.load().workspace_key() == b"\x01" * 32


def test_delete_removes_key_file():
    identity.generate()
    identity.delete()
    assert identity.load() is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/python -m pytest tests/client/test_identity.py -v`
Expected: FAIL — `module 'speechtotext.client' has no attribute 'identity'` / ImportError

- [ ] **Step 3: Implement `speechtotext/client/identity.py`**

```python
"""Device keypair storage for the hub client.

One JSON file, ``<app-data>/hub/device_key.json`` (mode 0600):

    {"signing_key_b64": ..., "workspace_key_b64": ...}

The Ed25519 signing key authenticates requests to the hub (wire scheme
v2, see speechtotext.api.auth). The workspace key arrives sealed to the
device's Curve25519 key during pairing and is stored after unsealing.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass

from speechtotext.client.paths import hub_dir


def _key_file():
    return hub_dir() / "device_key.json"


@dataclass
class DeviceIdentity:
    _signing_key_b64: str
    _workspace_key_b64: str | None = None

    def signing_key(self):
        from nacl.signing import SigningKey

        return SigningKey(base64.b64decode(self._signing_key_b64))

    def verify_key_b64(self) -> str:
        return base64.b64encode(
            self.signing_key().verify_key.encode()
        ).decode("ascii")

    def unseal(self, sealed: bytes) -> bytes:
        from nacl.public import SealedBox

        curve_sk = self.signing_key().to_curve25519_private_key()
        return SealedBox(curve_sk).decrypt(sealed)

    def store_workspace_key(self, key: bytes) -> None:
        self._workspace_key_b64 = base64.b64encode(key).decode("ascii")
        _save(self)

    def workspace_key(self) -> bytes | None:
        if self._workspace_key_b64 is None:
            return None
        return base64.b64decode(self._workspace_key_b64)


def _save(ident: DeviceIdentity) -> None:
    path = _key_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"signing_key_b64": ident._signing_key_b64}
    if ident._workspace_key_b64 is not None:
        payload["workspace_key_b64"] = ident._workspace_key_b64
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def generate() -> DeviceIdentity:
    from nacl.signing import SigningKey

    sk = SigningKey.generate()
    ident = DeviceIdentity(
        _signing_key_b64=base64.b64encode(sk.encode()).decode("ascii")
    )
    _save(ident)
    return ident


def load() -> DeviceIdentity | None:
    path = _key_file()
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return DeviceIdentity(
        _signing_key_b64=data["signing_key_b64"],
        _workspace_key_b64=data.get("workspace_key_b64"),
    )


def delete() -> None:
    try:
        _key_file().unlink()
    except FileNotFoundError:
        pass
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/python -m pytest tests/client/test_identity.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add speechtotext/client/identity.py speechtotext/client/paths.py tests/client/test_identity.py
git commit -m "feat(client): device identity storage with sealed workspace-key unwrap"
```

---

### Task 3: Client state (`state.py`)

**Files:**
- Create: `speechtotext/client/state.py`
- Test: `tests/client/test_state.py`

- [ ] **Step 1: Write failing tests**

`tests/client/test_state.py`:
```python
from speechtotext.client import state


def test_load_returns_none_when_not_joined():
    assert state.load() is None


def test_save_load_roundtrip():
    st = state.ClientState(
        hub_url="http://hub.tailnet:8010",
        workspace_id="ws-abc",
        device_id="dev-123456789abc",
        device_name="lieuwe-laptop",
        tls_spki_b64=None,
        cursor=0.0,
    )
    state.save(st)
    loaded = state.load()
    assert loaded == st


def test_update_cursor_persists():
    st = state.ClientState(
        hub_url="http://hub.tailnet:8010",
        workspace_id="ws-abc",
        device_id="dev-123456789abc",
        device_name="lieuwe-laptop",
        tls_spki_b64=None,
        cursor=0.0,
    )
    state.save(st)
    state.update_cursor(1234.5)
    assert state.load().cursor == 1234.5


def test_delete():
    st = state.ClientState(
        hub_url="u", workspace_id="w", device_id="d",
        device_name="n", tls_spki_b64=None, cursor=0.0,
    )
    state.save(st)
    state.delete()
    assert state.load() is None
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/python -m pytest tests/client/test_state.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement `speechtotext/client/state.py`**

```python
"""Joined-hub state: ``<app-data>/hub/client_state.json``.

Existence of this file == "this install is joined to a hub". The sync
cursor lives here (not in library.db) because it belongs to the hub
relationship, which `leave()` must delete atomically with the rest.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from speechtotext.client.paths import hub_dir


def _state_file():
    return hub_dir() / "client_state.json"


@dataclass
class ClientState:
    hub_url: str
    workspace_id: str
    device_id: str
    device_name: str
    tls_spki_b64: str | None
    cursor: float


def save(st: ClientState) -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(st)), encoding="utf-8")
    tmp.replace(path)


def load() -> ClientState | None:
    path = _state_file()
    if not path.exists():
        return None
    return ClientState(**json.loads(path.read_text(encoding="utf-8")))


def update_cursor(cursor: float) -> None:
    st = load()
    if st is None:
        return
    st.cursor = cursor
    save(st)


def delete() -> None:
    try:
        _state_file().unlink()
    except FileNotFoundError:
        pass
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/python -m pytest tests/client/test_state.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add speechtotext/client/state.py tests/client/test_state.py
git commit -m "feat(client): persisted joined-hub state with sync cursor"
```

---

### Task 4: Signed HTTP client (`hub_client.py`)

**Files:**
- Create: `speechtotext/client/hub_client.py`
- Test: `tests/client/test_hub_client.py`

The signing helper mirrors `tests/api/_signing.py` but lives in production code; both call `speechtotext.api.auth.build_signed_message`, the single source of truth for the wire bytes.

- [ ] **Step 1: Write failing tests**

`tests/client/test_hub_client.py`:
```python
import base64
import hashlib
import json

import httpx
from nacl.signing import SigningKey

from speechtotext.api.auth import build_signed_message
from speechtotext.client.hub_client import HubClient, signed_headers


def test_signed_headers_verify_against_canonical_message():
    sk = SigningKey.generate()
    body = b'{"x":1}'
    headers = signed_headers(sk, "dev-1", "PATCH", "/transcripts/t1", body)
    msg = build_signed_message(
        "PATCH", "/transcripts/t1", "",
        headers["X-Timestamp"], headers["X-Nonce"],
        hashlib.sha256(body).digest(),
    )
    sig = base64.b64decode(headers["X-Signature-B64"])
    sk.verify_key.verify(msg, sig)  # raises BadSignatureError on mismatch


def test_signed_headers_include_query_in_target():
    sk = SigningKey.generate()
    headers = signed_headers(
        sk, "dev-1", "POST", "/jobs/upload?filename=a.wav", b"AUDIO"
    )
    msg = build_signed_message(
        "POST", "/jobs/upload", "filename=a.wav",
        headers["X-Timestamp"], headers["X-Nonce"],
        hashlib.sha256(b"AUDIO").digest(),
    )
    sk.verify_key.verify(msg, base64.b64decode(headers["X-Signature-B64"]))


def _echo_transport():
    """httpx MockTransport that echoes method/path/headers back as JSON."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "method": request.method,
            "path": request.url.path,
            "query": request.url.query.decode(),
            "device": request.headers.get("X-Device-Id"),
            "has_sig": "X-Signature-B64" in request.headers,
            "body_len": len(request.read()),
        })
    return httpx.MockTransport(handler)


def test_client_get_sync_since_signs_request():
    sk = SigningKey.generate()
    client = HubClient(
        "http://hub:8010", "dev-1", sk, transport=_echo_transport()
    )
    out = client.get_json("/sync/since/0.0")
    assert out["device"] == "dev-1"
    assert out["has_sig"] is True
    assert out["path"] == "/sync/since/0.0"


def test_client_upload_streams_file(tmp_path):
    audio = tmp_path / "rec.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 100)
    sk = SigningKey.generate()
    client = HubClient(
        "http://hub:8010", "dev-1", sk, transport=_echo_transport()
    )
    out = client.upload_audio(audio)
    assert out["path"] == "/jobs/upload"
    assert out["query"] == "filename=rec.wav"
    assert out["body_len"] == 104
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/python -m pytest tests/client/test_hub_client.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement `speechtotext/client/hub_client.py`**

```python
"""Signed HTTP client for a paired hub.

All requests carry the v2 signature headers. The message bytes come from
:func:`speechtotext.api.auth.build_signed_message` — the same function the
hub verifies with, so client and server can never drift.

Uploads hash the file in one pass to build the signature, then stream the
file as the request body (two sequential disk reads, zero full-file RAM).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from pathlib import Path
from typing import Any

import httpx

from speechtotext.api.auth import build_signed_message

_CHUNK = 64 * 1024


def signed_headers(
    signing_key,
    device_id: str,
    method: str,
    path_with_query: str,
    body: bytes = b"",
    *,
    body_sha256: bytes | None = None,
) -> dict[str, str]:
    """v2 signature headers. ``path_with_query`` may include ``?query``.

    Pass ``body_sha256`` for streaming bodies (digest precomputed); else
    the digest is taken over ``body``.
    """
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    path, _, query = path_with_query.partition("?")
    digest = body_sha256 or hashlib.sha256(body).digest()
    msg = build_signed_message(method, path, query, ts, nonce, digest)
    sig = signing_key.sign(msg).signature
    return {
        "X-Device-Id": device_id,
        "X-Signature-B64": base64.b64encode(sig).decode("ascii"),
        "X-Timestamp": ts,
        "X-Nonce": nonce,
    }


def _file_sha256(path: Path) -> bytes:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.digest()


class HubClient:
    """Thin synchronous client. One instance per joined hub."""

    def __init__(
        self,
        base_url: str,
        device_id: str,
        signing_key,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.device_id = device_id
        self._sk = signing_key
        self._http = httpx.Client(
            base_url=self.base_url, timeout=timeout, transport=transport
        )

    def get_json(self, path_with_query: str) -> Any:
        headers = signed_headers(
            self._sk, self.device_id, "GET", path_with_query
        )
        resp = self._http.get(path_with_query, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def patch_json(self, path: str, body: dict) -> Any:
        import json as _json

        raw = _json.dumps(body).encode("utf-8")
        headers = signed_headers(self._sk, self.device_id, "PATCH", path, raw)
        headers["Content-Type"] = "application/json"
        resp = self._http.request("PATCH", path, content=raw, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def upload_audio(self, audio_path: Path) -> Any:
        digest = _file_sha256(audio_path)
        size = audio_path.stat().st_size
        target = f"/jobs/upload?filename={audio_path.name}"
        headers = signed_headers(
            self._sk, self.device_id, "POST", target, body_sha256=digest
        )
        headers["Content-Length"] = str(size)
        headers["Content-Type"] = "application/octet-stream"

        def _stream():
            with audio_path.open("rb") as fh:
                while chunk := fh.read(_CHUNK):
                    yield chunk

        resp = self._http.post(target, content=_stream(), headers=headers)
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._http.close()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/python -m pytest tests/client/test_hub_client.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add speechtotext/client/hub_client.py tests/client/test_hub_client.py
git commit -m "feat(client): signed hub HTTP client with streaming digest uploads"
```

---

### Task 5: Pairing string + join/leave (`join.py`)

**Files:**
- Create: `speechtotext/client/join.py`
- Test: `tests/client/test_join.py`

Pairing string = `base64(JSON PairingPayloadV1)`: `{"hub_url", "workspace_id", "token", "tls_spki_b64"?}` — same payload the phone scans as QR (`ui/src/lib/pairing.ts`). Join claims `POST /pair` (`speechtotext/api/routes_pairing.py:144`), which returns `{device_id, workspace_id, workspace_key_sealed_b64, lamport_observed}`.

- [ ] **Step 1: Write failing tests**

`tests/client/test_join.py`:
```python
import base64
import json
import os

import httpx
import pytest
from nacl.public import SealedBox
from nacl.signing import SigningKey

from speechtotext.client import identity, join, state


def _payload_str(**overrides) -> str:
    payload = {
        "hub_url": "http://hub.tailnet:8010",
        "workspace_id": "ws-abc",
        "token": "tok123",
        **overrides,
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


def test_decode_pairing_string_roundtrip():
    p = join.decode_pairing_string(_payload_str())
    assert p.hub_url == "http://hub.tailnet:8010"
    assert p.workspace_id == "ws-abc"
    assert p.token == "tok123"
    assert p.tls_spki_b64 is None


def test_decode_rejects_garbage():
    with pytest.raises(join.PairingStringError):
        join.decode_pairing_string("not base64 json!!")


def test_decode_rejects_missing_fields():
    bad = base64.b64encode(json.dumps({"hub_url": "x"}).encode()).decode()
    with pytest.raises(join.PairingStringError):
        join.decode_pairing_string(bad)


def _fake_hub_transport(workspace_key: bytes):
    """Answers POST /pair like the real hub: seals workspace_key to the
    submitted device pubkey."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/pair"
        body = json.loads(request.read())
        from nacl.signing import VerifyKey

        vk = VerifyKey(base64.b64decode(body["device_pubkey_b64"]))
        sealed = SealedBox(vk.to_curve25519_public_key()).encrypt(workspace_key)
        return httpx.Response(200, json={
            "device_id": "dev-feedbeef0001",
            "workspace_id": "ws-abc",
            "workspace_key_sealed_b64": base64.b64encode(sealed).decode(),
            "lamport_observed": 0,
        })
    return httpx.MockTransport(handler)


def test_join_persists_identity_and_state():
    wkey = os.urandom(32)
    st = join.join_hub(
        _payload_str(),
        device_name="lieuwe-laptop",
        transport=_fake_hub_transport(wkey),
    )
    assert st.device_id == "dev-feedbeef0001"
    assert state.load() == st
    ident = identity.load()
    assert ident is not None
    assert ident.workspace_key() == wkey


def test_leave_removes_identity_and_state():
    wkey = os.urandom(32)
    join.join_hub(
        _payload_str(), device_name="x",
        transport=_fake_hub_transport(wkey),
    )
    join.leave_hub()
    assert state.load() is None
    assert identity.load() is None
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/python -m pytest tests/client/test_join.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement `speechtotext/client/join.py`**

```python
"""Join/leave a hub.

Join: decode pasted pairing string → generate device identity → claim the
single-use token at ``POST /pair`` → unseal the workspace key → persist
identity + state. Any failure before persist leaves no partial state.

Leave: delete key + state. Synced transcripts stay on disk (spec: "keeps
synced transcripts").
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass

import httpx

from speechtotext.client import identity as identity_module
from speechtotext.client import state as state_module


class PairingStringError(ValueError):
    """Pasted pairing string is not a valid PairingPayloadV1."""


@dataclass(frozen=True)
class PairingPayload:
    hub_url: str
    workspace_id: str
    token: str
    tls_spki_b64: str | None = None


def decode_pairing_string(raw: str) -> PairingPayload:
    try:
        doc = json.loads(base64.b64decode(raw.strip(), validate=True))
    except (binascii.Error, ValueError) as exc:
        raise PairingStringError(f"not base64-encoded JSON: {exc}") from exc
    missing = {"hub_url", "workspace_id", "token"} - set(doc)
    if missing:
        raise PairingStringError(f"missing fields: {sorted(missing)}")
    return PairingPayload(
        hub_url=str(doc["hub_url"]).rstrip("/"),
        workspace_id=str(doc["workspace_id"]),
        token=str(doc["token"]),
        tls_spki_b64=doc.get("tls_spki_b64"),
    )


def join_hub(
    pairing_string: str,
    *,
    device_name: str,
    transport: httpx.BaseTransport | None = None,
) -> state_module.ClientState:
    payload = decode_pairing_string(pairing_string)
    ident = identity_module.generate()
    try:
        with httpx.Client(
            base_url=payload.hub_url, timeout=15.0, transport=transport
        ) as http:
            resp = http.post("/pair", json={
                "token": payload.token,
                "device_pubkey_b64": ident.verify_key_b64(),
                "device_name": device_name,
            })
            resp.raise_for_status()
            data = resp.json()
        workspace_key = ident.unseal(
            base64.b64decode(data["workspace_key_sealed_b64"])
        )
        ident.store_workspace_key(workspace_key)
    except Exception:
        # Pairing failed — roll back the freshly generated identity so a
        # retry starts clean and no orphan key file lingers.
        identity_module.delete()
        raise
    st = state_module.ClientState(
        hub_url=payload.hub_url,
        workspace_id=data["workspace_id"],
        device_id=data["device_id"],
        device_name=device_name,
        tls_spki_b64=payload.tls_spki_b64,
        cursor=0.0,
    )
    state_module.save(st)
    return st


def leave_hub() -> None:
    state_module.delete()
    identity_module.delete()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/python -m pytest tests/client/test_join.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add speechtotext/client/join.py tests/client/test_join.py
git commit -m "feat(client): pairing-string decode and hub join/leave flow"
```

---

### Task 6: Upload outbox (`upload_queue.py`)

**Files:**
- Create: `speechtotext/client/upload_queue.py`
- Test: `tests/client/test_upload_queue.py`

Disk outbox: `enqueue()` copies the audio file into `<app-data>/hub/outbox/` plus a `.meta.json` sidecar (`{"job_id": ...}` so the sidecar job record can be updated on completion). The `Uploader` drains oldest-first with exponential backoff; a failed batch stops the sweep (hub likely down) and the next sweep retries.

- [ ] **Step 1: Write failing tests**

`tests/client/test_upload_queue.py`:
```python
import json

import pytest

from speechtotext.client import upload_queue
from speechtotext.client.paths import outbox_dir


class FakeHubClient:
    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.uploaded: list[str] = []

    def upload_audio(self, path):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("hub down")
        self.uploaded.append(path.name)
        return {"job_id": "hub-job-1", "bytes_received": path.stat().st_size}


def _make_audio(tmp_path, name="a.wav"):
    p = tmp_path / name
    p.write_bytes(b"RIFF" + b"\x00" * 50)
    return p


def test_enqueue_copies_into_outbox(tmp_path):
    audio = _make_audio(tmp_path)
    entry = upload_queue.enqueue(audio, job_id="local-1")
    assert entry.audio_path.parent == outbox_dir()
    assert entry.audio_path.exists()
    meta = json.loads(entry.meta_path.read_text())
    assert meta["job_id"] == "local-1"
    assert audio.exists()  # source untouched


def test_pending_lists_oldest_first(tmp_path):
    e1 = upload_queue.enqueue(_make_audio(tmp_path, "one.wav"), job_id="j1")
    e2 = upload_queue.enqueue(_make_audio(tmp_path, "two.wav"), job_id="j2")
    names = [e.audio_path.name for e in upload_queue.pending()]
    assert names.index(e1.audio_path.name) < names.index(e2.audio_path.name)


def test_sweep_uploads_and_removes(tmp_path):
    upload_queue.enqueue(_make_audio(tmp_path), job_id="j1")
    hub = FakeHubClient()
    done = upload_queue.sweep(hub)
    assert len(done) == 1
    assert done[0].job_id == "j1"
    assert upload_queue.pending() == []
    assert hub.uploaded  # actually hit the client


def test_sweep_keeps_entry_on_failure(tmp_path):
    upload_queue.enqueue(_make_audio(tmp_path), job_id="j1")
    hub = FakeHubClient(fail_times=1)
    done = upload_queue.sweep(hub)
    assert done == []
    assert len(upload_queue.pending()) == 1
    # next sweep succeeds
    assert len(upload_queue.sweep(hub)) == 1


def test_sweep_stops_batch_after_first_failure(tmp_path):
    upload_queue.enqueue(_make_audio(tmp_path, "one.wav"), job_id="j1")
    upload_queue.enqueue(_make_audio(tmp_path, "two.wav"), job_id="j2")
    hub = FakeHubClient(fail_times=1)
    upload_queue.sweep(hub)
    # first failed -> batch stopped, both still pending
    assert len(upload_queue.pending()) == 2
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/python -m pytest tests/client/test_upload_queue.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement `speechtotext/client/upload_queue.py`**

```python
"""Disk-backed upload outbox.

Layout per entry (timestamp-prefixed so lexical order == FIFO):

    outbox/<stamp>-<rand>-<name>.wav          # the audio
    outbox/<stamp>-<rand>-<name>.wav.meta.json  # {"job_id": ...}

`sweep()` uploads oldest-first and deletes entries on 2xx. The first
failure aborts the batch: one unreachable hub shouldn't spin through N
files' worth of timeouts. The caller's retry loop (Task 8's runtime)
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
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    dest = root / f"{stamp}-{secrets.token_hex(4)}-{audio_path.name}"
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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/python -m pytest tests/client/test_upload_queue.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add speechtotext/client/upload_queue.py tests/client/test_upload_queue.py
git commit -m "feat(client): disk-backed upload outbox with fail-safe sweep"
```

---

### Task 7: Sync puller (`sync_puller.py`)

**Files:**
- Create: `speechtotext/client/sync_puller.py`
- Test: `tests/client/test_sync_puller.py`

Pull one round: `GET /sync/since/{cursor}` (or paged `/sync/snapshot` when cursor is 0), write each doc to `<app-data>/hub/synced/<id>.json` (strip the wire-injected `"id"` key — the filename stem IS the id, matching hub disk layout), persist the new cursor. The caller wires re-indexing (Task 8).

- [ ] **Step 1: Write failing tests**

`tests/client/test_sync_puller.py`:
```python
import json

from speechtotext.client import state, sync_puller
from speechtotext.client.paths import synced_dir


def _joined_state(cursor=0.0):
    st = state.ClientState(
        hub_url="http://hub:8010", workspace_id="ws", device_id="dev-1",
        device_name="laptop", tls_spki_b64=None, cursor=cursor,
    )
    state.save(st)
    return st


class FakeHub:
    def __init__(self, pages):
        self.pages = pages  # list of responses to return in order
        self.calls: list[str] = []

    def get_json(self, path):
        self.calls.append(path)
        return self.pages.pop(0)


def _doc(tid, mtime, text="hello"):
    return {
        "id": tid,
        "segments": [{"speaker": "SPEAKER_00", "text": text}],
        "_mtime": mtime,
    }


def test_pull_once_writes_docs_and_advances_cursor():
    _joined_state(cursor=100.0)
    hub = FakeHub([{
        "workspace_id": "ws", "cursor": 200.0,
        "transcripts": [_doc("t1", 150.0), _doc("t2", 200.0)],
    }])
    written = sync_puller.pull_once(hub)
    assert sorted(p.name for p in written) == ["t1.json", "t2.json"]
    assert hub.calls == ["/sync/since/100.0"]
    assert state.load().cursor == 200.0
    saved = json.loads((synced_dir() / "t1.json").read_text())
    assert "id" not in saved
    assert saved["segments"][0]["text"] == "hello"


def test_pull_once_uses_snapshot_on_first_sync():
    _joined_state(cursor=0.0)
    hub = FakeHub([{
        "workspace_id": "ws", "cursor": 50.0,
        "transcripts": [_doc("t1", 50.0)],
    }])
    sync_puller.pull_once(hub)
    assert hub.calls[0].startswith("/sync/snapshot")


def test_pull_once_empty_delta_still_advances_cursor():
    _joined_state(cursor=100.0)
    hub = FakeHub([{
        "workspace_id": "ws", "cursor": 300.0, "transcripts": [],
    }])
    written = sync_puller.pull_once(hub)
    assert written == []
    assert state.load().cursor == 300.0


def test_pull_once_not_joined_is_noop():
    hub = FakeHub([])
    assert sync_puller.pull_once(hub) == []
    assert hub.calls == []
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/python -m pytest tests/client/test_sync_puller.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement `speechtotext/client/sync_puller.py`**

```python
"""Pull hub transcripts into the local synced dir.

One round = one HTTP call. First sync (cursor 0) uses ``/sync/snapshot``;
after that ``/sync/since/{cursor}``. Docs land as
``<app-data>/hub/synced/<id>.json`` — the same id-as-filename-stem layout
the hub uses, so the local LibraryDB indexes them exactly like local
transcripts. The wire-injected ``id`` key is stripped before writing
(filename stem is canonical; see routes_sync.py "Mobile clients require
it to key rows").

The periodic loop lives in the sidecar runtime (hub_runtime.py), not
here — this module stays synchronous and unit-testable.
"""

from __future__ import annotations

import json
from pathlib import Path

from speechtotext.client import state as state_module
from speechtotext.client.paths import synced_dir


def pull_once(hub_client) -> list[Path]:
    st = state_module.load()
    if st is None:
        return []
    if st.cursor <= 0.0:
        payload = hub_client.get_json("/sync/snapshot")
    else:
        payload = hub_client.get_json(f"/sync/since/{st.cursor}")

    root = synced_dir()
    written: list[Path] = []
    for doc in payload.get("transcripts", []):
        doc = dict(doc)
        tid = doc.pop("id", None)
        if not tid:
            continue
        root.mkdir(parents=True, exist_ok=True)
        dest = root / f"{tid}.json"
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(dest)
        written.append(dest)

    new_cursor = float(payload.get("cursor", st.cursor))
    if new_cursor > st.cursor:
        state_module.update_cursor(new_cursor)
    return written
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/python -m pytest tests/client/test_sync_puller.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add speechtotext/client/sync_puller.py tests/client/test_sync_puller.py
git commit -m "feat(client): sync puller writing hub transcripts to synced dir"
```

---

### Task 8: Client runtime (threads) (`hub_runtime.py`)

**Files:**
- Create: `speechtotext/client/hub_runtime.py`
- Test: `tests/client/test_hub_runtime.py`

One object owning the joined lifecycle: builds the `HubClient` from persisted identity+state, runs uploader + puller on a single background thread (30 s period, `threading.Event` for prompt shutdown and `poke()` for immediate sweep after enqueue), and reports status for the UI. Job records are updated via callbacks so the runtime has no FastAPI dependency.

- [ ] **Step 1: Write failing tests**

`tests/client/test_hub_runtime.py`:
```python
import time

from speechtotext.client import hub_runtime, identity, state


def _join_locally():
    identity.generate()
    st = state.ClientState(
        hub_url="http://hub:8010", workspace_id="ws", device_id="dev-1",
        device_name="laptop", tls_spki_b64=None, cursor=100.0,
    )
    state.save(st)
    return st


class FakeHubClient:
    def __init__(self):
        self.uploads = []

    def upload_audio(self, path):
        self.uploads.append(path.name)
        return {"job_id": "h1", "bytes_received": 1}

    def get_json(self, path):
        return {"workspace_id": "ws", "cursor": 100.0, "transcripts": []}

    def close(self):
        pass


def test_runtime_not_joined_reports_status():
    rt = hub_runtime.HubRuntime()
    assert rt.status()["joined"] is False


def test_runtime_joined_status_includes_hub_url():
    _join_locally()
    rt = hub_runtime.HubRuntime()
    s = rt.status()
    assert s["joined"] is True
    assert s["hub_url"] == "http://hub:8010"
    assert s["pending_uploads"] == 0


def test_enqueue_and_sweep_via_poke(tmp_path):
    _join_locally()
    audio = tmp_path / "rec.wav"
    audio.write_bytes(b"RIFF00")
    fake = FakeHubClient()
    sent = []
    rt = hub_runtime.HubRuntime(
        hub_client_factory=lambda st, ident: fake,
        on_entry_sent=lambda entry: sent.append(entry.job_id),
        period_s=3600.0,  # only poke triggers work in this test
    )
    rt.start()
    try:
        rt.enqueue_upload(audio, job_id="local-7")
        rt.poke()
        deadline = time.time() + 5.0
        while time.time() < deadline and not sent:
            time.sleep(0.02)
        assert sent == ["local-7"]
        assert len(fake.uploads) == 1  # the outbox copy was uploaded
        assert rt.status()["pending_uploads"] == 0
    finally:
        rt.stop()


def test_stop_terminates_thread_quickly():
    _join_locally()
    rt = hub_runtime.HubRuntime(
        hub_client_factory=lambda st, ident: FakeHubClient(),
        period_s=3600.0,
    )
    rt.start()
    t0 = time.time()
    rt.stop()
    assert time.time() - t0 < 2.0
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/python -m pytest tests/client/test_hub_runtime.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement `speechtotext/client/hub_runtime.py`**

```python
"""Background runtime for a joined hub: uploader sweep + sync pull.

Single daemon thread; each cycle sweeps the outbox then pulls sync.
``poke()`` wakes the thread immediately (used right after an enqueue so
uploads don't wait for the next period). ``stop()`` sets the event and
joins the thread.

No FastAPI imports here — the sidecar wires callbacks (Task 9) to update
job records and re-index the library.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from speechtotext.client import identity as identity_module
from speechtotext.client import state as state_module
from speechtotext.client import sync_puller, upload_queue
from speechtotext.client.hub_client import HubClient
from speechtotext.client.upload_queue import OutboxEntry

DEFAULT_PERIOD_S = 30.0


def _default_factory(st, ident) -> HubClient:
    return HubClient(st.hub_url, st.device_id, ident.signing_key())


class HubRuntime:
    def __init__(
        self,
        *,
        hub_client_factory: Callable = _default_factory,
        on_entry_sent: Callable[[OutboxEntry], None] | None = None,
        on_synced: Callable[[list[Path]], None] | None = None,
        period_s: float = DEFAULT_PERIOD_S,
    ) -> None:
        self._factory = hub_client_factory
        self._on_entry_sent = on_entry_sent
        self._on_synced = on_synced
        self._period = period_s
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None
        self._last_sync_at: float | None = None

    # -- lifecycle -------------------------------------------------------
    def joined(self) -> bool:
        return state_module.load() is not None

    def start(self) -> None:
        if self._thread is not None or not self.joined():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="hub-runtime", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def poke(self) -> None:
        self._wake.set()

    # -- work ------------------------------------------------------------
    def enqueue_upload(self, audio_path: Path, *, job_id: str | None) -> None:
        upload_queue.enqueue(audio_path, job_id=job_id)

    def status(self) -> dict:
        st = state_module.load()
        if st is None:
            return {"joined": False}
        return {
            "joined": True,
            "hub_url": st.hub_url,
            "workspace_id": st.workspace_id,
            "device_id": st.device_id,
            "device_name": st.device_name,
            "cursor": st.cursor,
            "pending_uploads": len(upload_queue.pending()),
            "last_error": self._last_error,
            "last_sync_at": self._last_sync_at,
        }

    def _run(self) -> None:
        import time as _time

        while not self._stop.is_set():
            st = state_module.load()
            ident = identity_module.load()
            if st is None or ident is None:
                break  # left the hub while running
            client = None
            try:
                client = self._factory(st, ident)
                sent = upload_queue.sweep(client)
                if self._on_entry_sent:
                    for entry in sent:
                        self._on_entry_sent(entry)
                written = sync_puller.pull_once(client)
                if written and self._on_synced:
                    self._on_synced(written)
                self._last_error = None
                self._last_sync_at = _time.time()
            except Exception as exc:  # network errors -> retry next cycle
                self._last_error = f"{type(exc).__name__}: {exc}"
            finally:
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass
            self._wake.wait(timeout=self._period)
            self._wake.clear()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/python -m pytest tests/client/test_hub_runtime.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add speechtotext/client/hub_runtime.py tests/client/test_hub_runtime.py
git commit -m "feat(client): background hub runtime sweeping uploads and pulling sync"
```

---

### Task 9: `origin` column in LibraryDB

**Files:**
- Modify: `speechtotext/api/library_db.py` (DDL at :59, `LibraryDB.__init__` at :220, `_migrate` at :232, `upsert_path` at :248, `_row_to_item` at :524)
- Test: `tests/api/test_library_db_origin.py`

`LibraryDB` gains an optional `hub_synced_dir` constructor arg; `upsert_path` stores `origin='hub'` when the json path is under it, else `'local'`. `_row_to_item` exposes `origin`. Existing DBs get the column via a guarded `ALTER TABLE`.

- [ ] **Step 1: Write failing tests**

`tests/api/test_library_db_origin.py`:
```python
import json
from pathlib import Path

from speechtotext.api.library_db import LibraryDB


def _write_doc(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "audio_path": "/x/a.wav",
        "segments": [{"speaker": "SPEAKER_00", "text": "hi"}],
    }), encoding="utf-8")


def test_local_doc_gets_origin_local(tmp_path):
    db = LibraryDB(tmp_path / "lib.db")
    doc = tmp_path / "out" / "a.json"
    _write_doc(doc)
    db.upsert_path(doc)
    items = db.list()
    assert items[0]["origin"] == "local"


def test_hub_synced_doc_gets_origin_hub(tmp_path):
    synced = tmp_path / "hub" / "synced"
    db = LibraryDB(tmp_path / "lib.db", hub_synced_dir=synced)
    doc = synced / "t1.json"
    _write_doc(doc)
    db.upsert_path(doc)
    assert db.list()[0]["origin"] == "hub"


def test_existing_db_migrates_origin_column(tmp_path):
    # Create a DB with the current code, then reopen — must not raise
    # and rows must default to 'local'.
    db_path = tmp_path / "lib.db"
    db = LibraryDB(db_path)
    doc = tmp_path / "a.json"
    _write_doc(doc)
    db.upsert_path(doc)
    db.close()
    db2 = LibraryDB(db_path)
    assert db2.list()[0]["origin"] == "local"
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/python -m pytest tests/api/test_library_db_origin.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'hub_synced_dir'` (first test may fail on missing `origin` key)

- [ ] **Step 3: Implement**

In `speechtotext/api/library_db.py`:

1. Add to the `transcripts` DDL (inside the `CREATE TABLE IF NOT EXISTS transcripts` statement, after `error           TEXT,`):
```sql
        origin          TEXT NOT NULL DEFAULT 'local',
```

2. `__init__` gains the kwarg and stores it:
```python
    def __init__(
        self, db_path: Path | None = None, *,
        hub_synced_dir: Path | None = None,
    ) -> None:
        self._hub_synced_dir = (
            hub_synced_dir.resolve() if hub_synced_dir else None
        )
        # ... existing body unchanged below
```

3. In `_migrate` (after existing migration steps), add the guarded column add — new tables already have it from the DDL; old DBs get it here:
```python
        try:
            self._conn.execute(
                "ALTER TABLE transcripts "
                "ADD COLUMN origin TEXT NOT NULL DEFAULT 'local'"
            )
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
```

4. In `upsert_path`, compute origin and include it in the INSERT/UPDATE column lists (adapt to the existing SQL in that method — add `origin` to the column tuple and the parameter tuple):
```python
        origin = "local"
        if self._hub_synced_dir is not None:
            try:
                json_path.resolve().relative_to(self._hub_synced_dir)
                origin = "hub"
            except ValueError:
                pass
```

5. In `_row_to_item`, add:
```python
        "origin": r["origin"] if "origin" in r.keys() else "local",
```

- [ ] **Step 4: Run new tests + full library suite**

Run: `.venv/bin/python -m pytest tests/api/test_library_db_origin.py tests/api -k "library" -v`
Expected: new tests pass, zero regressions in existing library tests

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/library_db.py tests/api/test_library_db_origin.py
git commit -m "feat(api): origin column on transcripts index (local vs hub-synced)"
```

---

### Task 10: Sidecar wiring — `/client/hub/*` routes + joined-mode job routing

**Files:**
- Create: `speechtotext/api/routes_client.py`
- Modify: `speechtotext/api/app.py` (state at :157-177, router includes at :207-216, `_lifespan` at :117)
- Modify: `speechtotext/api/routes_jobs.py:21-35` (`post_transcribe`)
- Test: `tests/api/test_routes_client.py`

- [ ] **Step 1: Write failing tests**

`tests/api/test_routes_client.py`:
```python
import base64
import json

from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


def _client(tmp_path):
    app = create_app(library_db_path=tmp_path / "lib.db")
    return app, TestClient(app)


def _pairing_string(hub_url: str) -> str:
    # Mint a real token from the same app acting as the hub, then encode
    # the payload the way the desktop UI / CLI would.
    return base64.b64encode(json.dumps({
        "hub_url": hub_url, "workspace_id": "ws-x", "token": "TOK",
    }).encode()).decode()


def test_hub_status_not_joined(tmp_path):
    _, client = _client(tmp_path)
    resp = client.get("/client/hub")
    assert resp.status_code == 200
    assert resp.json() == {"joined": False}


def test_join_against_self_and_status_and_leave(tmp_path):
    # The app under test is both hub and client: mint a token on it,
    # join it via loopback pairing, then verify status flips.
    app, client = _client(tmp_path)
    tok = client.post("/pair/tokens").json()["token"]
    payload = base64.b64encode(json.dumps({
        "hub_url": str(client.base_url),
        "workspace_id": "ws-x",
        "token": tok,
    }).encode()).decode()

    import httpx
    from speechtotext.api import routes_client
    # Route the client package's outbound pairing call into the ASGI app
    # instead of the network.
    routes_client._TEST_TRANSPORT = httpx.ASGITransport(app=app)
    try:
        resp = client.post("/client/hub/join", json={
            "pairing_string": payload, "device_name": "test-laptop",
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["joined"] is True
        assert body["device_id"].startswith("dev-")

        status = client.get("/client/hub").json()
        assert status["joined"] is True
        assert status["pending_uploads"] == 0

        resp = client.post("/client/hub/leave")
        assert resp.status_code == 200
        assert client.get("/client/hub").json() == {"joined": False}
    finally:
        routes_client._TEST_TRANSPORT = None


def test_join_with_bad_pairing_string_is_400(tmp_path):
    _, client = _client(tmp_path)
    resp = client.post("/client/hub/join", json={
        "pairing_string": "garbage", "device_name": "x",
    })
    assert resp.status_code == 400


def test_transcribe_routes_to_outbox_when_joined(tmp_path, monkeypatch):
    app, client = _client(tmp_path)
    tok = client.post("/pair/tokens").json()["token"]
    payload = base64.b64encode(json.dumps({
        "hub_url": str(client.base_url), "workspace_id": "ws-x",
        "token": tok,
    }).encode()).decode()

    import httpx
    from speechtotext.api import routes_client
    routes_client._TEST_TRANSPORT = httpx.ASGITransport(app=app)
    try:
        client.post("/client/hub/join", json={
            "pairing_string": payload, "device_name": "x",
        })
        audio = tmp_path / "drop.wav"
        audio.write_bytes(b"RIFF" + b"\x00" * 64)
        resp = client.post("/jobs/transcribe", json={"path": str(audio)})
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        job = client.get(f"/jobs/{job_id}").json()
        assert job["kind"] == "hub_upload"
        assert client.get("/client/hub").json()["pending_uploads"] == 1
    finally:
        routes_client._TEST_TRANSPORT = None
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/python -m pytest tests/api/test_routes_client.py -v`
Expected: FAIL — 404 on `/client/hub` (router not included) / ImportError

- [ ] **Step 3: Implement `speechtotext/api/routes_client.py`**

```python
"""Loopback endpoints for the desktop UI to manage hub-client mode.

These are hub-*client* controls (join/leave/status), distinct from the
hub-*server* routes (pairing mint, sync). They are not in the LAN-signed
route set, so the existing bearer middleware gates them like the other
admin endpoints.

``_TEST_TRANSPORT`` lets tests route the outbound pairing/upload HTTP
into an in-process ASGI app; production leaves it None.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from speechtotext.client import join as join_module
from speechtotext.client.hub_client import HubClient
from speechtotext.client.hub_runtime import HubRuntime

router = APIRouter()

_TEST_TRANSPORT: httpx.BaseTransport | None = None


class JoinRequest(BaseModel):
    pairing_string: str = Field(min_length=1)
    device_name: str = Field(min_length=1, max_length=128)


def _runtime(request: Request) -> HubRuntime:
    return request.app.state.hub_runtime


@router.get("/client/hub")
def hub_status(request: Request) -> dict:
    status = _runtime(request).status()
    if not status["joined"]:
        return {"joined": False}
    return status


@router.post("/client/hub/join")
def hub_join(req: JoinRequest, request: Request) -> dict:
    runtime = _runtime(request)
    if runtime.joined():
        raise HTTPException(status_code=409, detail="already joined a hub")
    try:
        st = join_module.join_hub(
            req.pairing_string,
            device_name=req.device_name,
            transport=_TEST_TRANSPORT,
        )
    except join_module.PairingStringError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"hub rejected pairing: {exc.response.status_code}",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"cannot reach hub: {exc}"
        )
    runtime.start()
    return {"joined": True, "device_id": st.device_id,
            "hub_url": st.hub_url, "workspace_id": st.workspace_id}


@router.post("/client/hub/leave")
def hub_leave(request: Request) -> dict:
    runtime = _runtime(request)
    runtime.stop()
    join_module.leave_hub()
    return {"joined": False}
```

- [ ] **Step 4: Wire into `app.py`**

In `create_app` (near the other `app.state` assignments, `speechtotext/api/app.py:157-177`):
```python
    from speechtotext.client.hub_client import HubClient as _HubClient
    from speechtotext.client.hub_runtime import HubRuntime
    from speechtotext.client.paths import synced_dir

    def _client_factory(st, ident):
        from speechtotext.api import routes_client

        return _HubClient(
            st.hub_url, st.device_id, ident.signing_key(),
            transport=routes_client._TEST_TRANSPORT,
        )

    def _on_entry_sent(entry) -> None:
        if entry.job_id is None:
            return
        try:
            rec = app.state.jobs.get(entry.job_id)
        except KeyError:
            return
        from speechtotext.api.jobs import JobStatus

        rec.status = JobStatus.complete
        rec.stage = "sent-to-hub"
        rec.percent = 100.0

    def _on_synced(paths) -> None:
        app.state.library_dirs.add(synced_dir())
        app.state.library_db.sync_dirs(list(app.state.library_dirs))

    app.state.hub_runtime = HubRuntime(
        hub_client_factory=_client_factory,
        on_entry_sent=_on_entry_sent,
        on_synced=_on_synced,
    )
```

Pass the synced dir to LibraryDB (same function, where `app.state.library_db` is constructed at :160):
```python
    app.state.library_db = LibraryDB(
        library_db_path, hub_synced_dir=synced_dir()
    )
```

Also add `synced_dir()` to `app.state.library_dirs` at startup when it exists:
```python
    if synced_dir().exists():
        app.state.library_dirs.add(synced_dir())
```

Include the router alongside the others (`app.py:207-216`):
```python
    app.include_router(client_router)
```
with the import `from speechtotext.api.routes_client import router as client_router` next to the other route imports.

In `_lifespan` (app.py:117), start/stop the runtime:
```python
    app.state.hub_runtime.start()   # no-op when not joined
    yield                            # (merge with existing lifespan body)
    app.state.hub_runtime.stop()
```
(The existing `_lifespan` already has a body — add the `start()` before its `yield` and `stop()` after.)

- [ ] **Step 5: Route joined-mode transcribe to the outbox**

In `speechtotext/api/routes_jobs.py`, `post_transcribe` (line 21), insert after the audio-exists check:
```python
    runtime = getattr(request.app.state, "hub_runtime", None)
    if runtime is not None and runtime.joined():
        registry = request.app.state.jobs
        job_id = registry.create(kind="hub_upload", audio_path=str(audio))
        runtime.enqueue_upload(audio, job_id=job_id)
        runtime.poke()
        rec = registry.get(job_id)
        rec.stage = "queued-for-hub"
        return {"job_id": job_id}
```

Apply the same guard to the watch-folder dispatch: find where `speechtotext/api/routes_watch.py` (or the `WatchController` callback in `app.py`) calls `runner.run_transcribe_job`, and route through the identical `runtime.joined()` branch. Same code shape: create `kind="hub_upload"` job, `enqueue_upload`, `poke()`.

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/api/test_routes_client.py tests/api/test_jobs.py tests/api/test_app.py -v`
Expected: new tests pass, no regressions

- [ ] **Step 7: Commit**

```bash
git add speechtotext/api/routes_client.py speechtotext/api/app.py speechtotext/api/routes_jobs.py speechtotext/api/routes_watch.py tests/api/test_routes_client.py
git commit -m "feat(api): hub-client routes and joined-mode upload routing in sidecar"
```

---

### Task 11: Relabel routing for hub-origin transcripts

**Files:**
- Modify: `speechtotext/api/routes_transcripts.py` (the relabel/PATCH-adjacent handler the desktop UI calls — locate the loopback relabel endpoint in this file)
- Test: `tests/api/test_relabel_hub_origin.py`

When the UI relabels a transcript whose `origin == "hub"`, the sidecar must forward a CRDT relabel op to the hub (`PATCH /transcripts/{tid}` signed with the device key) instead of rewriting the local synced file (which the next sync would clobber anyway). Local-origin relabels keep the existing behavior.

- [ ] **Step 1: Write failing test**

`tests/api/test_relabel_hub_origin.py`:
```python
import base64
import json

from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


def _joined_app_pair(tmp_path):
    """One app instance acting as both hub and (joined) client, with the
    test transport looping outbound calls back into itself."""
    import httpx
    from speechtotext.api import routes_client

    app = create_app(library_db_path=tmp_path / "lib.db")
    client = TestClient(app)
    routes_client._TEST_TRANSPORT = httpx.ASGITransport(app=app)
    tok = client.post("/pair/tokens").json()["token"]
    payload = base64.b64encode(json.dumps({
        "hub_url": str(client.base_url), "workspace_id": "ws-x",
        "token": tok,
    }).encode()).decode()
    client.post("/client/hub/join", json={
        "pairing_string": payload, "device_name": "x",
    })
    return app, client


def test_relabel_hub_origin_forwards_crdt_patch(tmp_path):
    from speechtotext.client.paths import synced_dir

    app, client = _joined_app_pair(tmp_path)
    try:
        # Plant a hub-origin transcript in the synced dir and index it.
        doc_dir = synced_dir()
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / "t1.json").write_text(json.dumps({
            "audio_path": "/x/a.wav",
            "segments": [{"speaker": "SPEAKER_00", "text": "hi"}],
            "speaker_names": {},
            "clocks": {},
        }), encoding="utf-8")
        app.state.library_dirs.add(doc_dir)
        app.state.library_db.sync_dirs([doc_dir])

        # Relabel through the sidecar's UI-facing endpoint. Because the
        # transcript is hub-origin and this app IS the hub (loopback test
        # transport), the CRDT op round-trips and the hub-side handler
        # applies it — assert the relabel landed.
        resp = client.patch("/transcripts/t1", json={
            "op": "relabel",
            "field": "SPEAKER_00",
            "value": "Alice",
            "lamport_observed": 0,
        })
        assert resp.status_code in (200, 202), resp.text
    finally:
        from speechtotext.api import routes_client
        routes_client._TEST_TRANSPORT = None
```

**Note to implementer:** before writing this test, read the actual relabel request/response models in `speechtotext/api/routes_transcripts.py:30-65` and `speechtotext/api/crdt.py`, and adjust the JSON body above to the real CRDT op shape. The assertion strategy stands: hub-origin relabel through the sidecar must succeed end-to-end via the signed forward path.

- [ ] **Step 2: Run test, verify fail**

Run: `.venv/bin/python -m pytest tests/api/test_relabel_hub_origin.py -v`
Expected: FAIL (endpoint either rejects the unsigned local PATCH for hub-origin or applies it locally without forwarding — observe actual behavior and pin the failure)

- [ ] **Step 3: Implement forwarding**

In the sidecar's relabel handler in `routes_transcripts.py`: look up the transcript's `origin` via `request.app.state.library_db` (`_row_to_item` now returns it, Task 9). If `origin == "hub"` and `request.app.state.hub_runtime.joined()`:

```python
    from speechtotext.client import identity as _identity
    from speechtotext.client import state as _state
    from speechtotext.api import routes_client as _rc
    from speechtotext.client.hub_client import HubClient

    st = _state.load()
    ident = _identity.load()
    if st is None or ident is None:
        raise HTTPException(status_code=409, detail="hub state missing")
    hub = HubClient(
        st.hub_url, st.device_id, ident.signing_key(),
        transport=_rc._TEST_TRANSPORT,
    )
    try:
        return hub.patch_json(f"/transcripts/{transcript_id}", body_dict)
    finally:
        hub.close()
```
where `body_dict` is the validated request body re-serialized. Local-origin path stays untouched.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/api/test_relabel_hub_origin.py tests/api/test_crdt.py -v`
Expected: pass, no CRDT regressions

- [ ] **Step 5: Commit**

```bash
git add speechtotext/api/routes_transcripts.py tests/api/test_relabel_hub_origin.py
git commit -m "feat(api): forward hub-origin relabels as signed CRDT ops"
```

---

### Task 12: `locallexis-hub pair` CLI

**Files:**
- Create: `speechtotext/api/hub_cli.py`
- Modify: `pyproject.toml:47` (console script target), `pyproject.toml` `[project.optional-dependencies] api` (add `qrcode>=7.4`)
- Test: `tests/api/test_hub_cli.py`

- [ ] **Step 1: Write failing tests**

`tests/api/test_hub_cli.py`:
```python
import base64
import json

from typer.testing import CliRunner

from speechtotext.api import hub_cli

runner = CliRunner()


def test_pair_prints_pairing_string(monkeypatch):
    def fake_mint(url, token):
        assert url == "http://127.0.0.1:8010"
        assert token == "admintok"
        return {"token": "PAIRTOK", "workspace_id": "ws-1",
                "expires_at": 0, "ttl_seconds": 300}

    monkeypatch.setattr(hub_cli, "_mint_token", fake_mint)
    monkeypatch.setenv("LOCALLEXIS_API_TOKEN", "admintok")
    monkeypatch.setenv("LOCALLEXIS_PORT", "8010")

    result = runner.invoke(
        hub_cli.app, ["pair", "--url", "http://hub.tailnet:8010", "--no-qr"]
    )
    assert result.exit_code == 0, result.output
    # The pairing string is the last non-empty line; decode and check.
    line = [l for l in result.output.splitlines() if l.strip()][-1]
    payload = json.loads(base64.b64decode(line.strip()))
    assert payload == {
        "hub_url": "http://hub.tailnet:8010",
        "workspace_id": "ws-1",
        "token": "PAIRTOK",
    }


def test_pair_requires_admin_token(monkeypatch):
    monkeypatch.delenv("LOCALLEXIS_API_TOKEN", raising=False)
    result = runner.invoke(
        hub_cli.app, ["pair", "--url", "http://hub:8010", "--no-qr"]
    )
    assert result.exit_code != 0
    assert "LOCALLEXIS_API_TOKEN" in result.output
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/python -m pytest tests/api/test_hub_cli.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement `speechtotext/api/hub_cli.py`**

```python
"""Console entry for ``locallexis-hub``.

``locallexis-hub``            → headless server (unchanged behavior)
``locallexis-hub serve``      → same, explicit
``locallexis-hub pair``       → mint a pairing token via the loopback API
                                and print the pairing string (+ QR).

``pair`` exists for headless installs where there is no desktop UI to
compose the QR. It talks to the *running* hub over loopback using the
admin bearer token from LOCALLEXIS_API_TOKEN.
"""

from __future__ import annotations

import base64
import json
import os

import typer

app = typer.Typer(
    no_args_is_help=False,
    invoke_without_command=True,
    help="LocalLexis headless hub.",
)


@app.callback()
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        serve()


@app.command()
def serve() -> None:
    """Run the headless hub server (default when no subcommand given)."""
    from speechtotext.api.server import headless

    headless()


def _mint_token(loopback_url: str, admin_token: str) -> dict:
    import httpx

    resp = httpx.post(
        f"{loopback_url}/pair/tokens",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()


@app.command()
def pair(
    url: str = typer.Option(
        ...,
        "--url",
        help=(
            "Hub URL as DEVICES reach it, e.g. http://hub.tailnet:8010. "
            "Goes into the pairing payload verbatim."
        ),
    ),
    name_hint: str = typer.Option(
        "", "--note", help="Optional note printed alongside the token."
    ),
    qr: bool = typer.Option(True, "--qr/--no-qr", help="Print an ASCII QR."),
) -> None:
    """Mint a single-use pairing token and print the pairing string."""
    admin_token = os.environ.get("LOCALLEXIS_API_TOKEN", "").strip()
    if not admin_token:
        typer.echo(
            "LOCALLEXIS_API_TOKEN is not set — the pair command talks to "
            "the running hub over loopback and needs the admin token.",
            err=True,
        )
        raise typer.Exit(code=2)
    port = os.environ.get("LOCALLEXIS_PORT", "8765").strip()
    loopback = f"http://127.0.0.1:{port}"

    minted = _mint_token(loopback, admin_token)
    payload = {
        "hub_url": url.rstrip("/"),
        "workspace_id": minted["workspace_id"],
        "token": minted["token"],
    }
    pairing_string = base64.b64encode(
        json.dumps(payload).encode("utf-8")
    ).decode("ascii")

    typer.echo(f"Pairing token minted (valid {minted['ttl_seconds']}s).")
    if name_hint:
        typer.echo(f"Note: {name_hint}")
    if qr:
        try:
            import qrcode

            q = qrcode.QRCode(border=1)
            q.add_data(json.dumps(payload))
            q.make(fit=True)
            q.print_ascii(invert=True)
        except ImportError:
            typer.echo("(install 'qrcode' for an ASCII QR)", err=True)
    typer.echo("Paste this into the desktop app's 'Join a hub' field:")
    typer.echo("")
    typer.echo(pairing_string)


def main() -> None:
    app()
```

- [ ] **Step 4: Update `pyproject.toml`**

```toml
[project.scripts]
stt = "speechtotext.cli:app"
locallexis-hub = "speechtotext.api.hub_cli:main"
```
and in `[project.optional-dependencies] api`, add:
```toml
    "qrcode>=7.4",
```

- [ ] **Step 5: Run tests + verify default path still serves**

Run: `.venv/bin/python -m pytest tests/api/test_hub_cli.py tests/api/test_server_headless.py -v`
Expected: pass (headless behavior untouched — `serve` delegates to the existing `server.headless`)

- [ ] **Step 6: Commit**

```bash
git add speechtotext/api/hub_cli.py pyproject.toml tests/api/test_hub_cli.py
git commit -m "feat(api): locallexis-hub pair subcommand printing pairing string + QR"
```

---

### Task 13: End-to-end integration test

**Files:**
- Test: `tests/api/test_hub_client_e2e.py`

Two `create_app` instances in one process: `hub_app` (the server) and `laptop_app` (the joined client), outbound calls routed via `httpx.ASGITransport(app=hub_app)`. The upload leg stubs the transcription runner (no ML models in tests) — the hub writes a transcript JSON as if a job completed, then the laptop's sync pull picks it up.

- [ ] **Step 1: Write the test**

`tests/api/test_hub_client_e2e.py`:
```python
import base64
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


@pytest.fixture()
def hub_and_laptop(tmp_path, monkeypatch):
    from speechtotext.api import routes_client

    hub_app = create_app(library_db_path=tmp_path / "hub-lib.db")
    hub = TestClient(hub_app)

    # Laptop app-data must be separate from the hub's — retarget the
    # client package to a second temp dir for this test.
    import speechtotext.client.paths as _paths

    laptop_data = tmp_path / "laptop-data"
    monkeypatch.setattr(_paths, "default_app_data_dir", lambda: laptop_data)

    laptop_app = create_app(library_db_path=tmp_path / "laptop-lib.db")
    laptop = TestClient(laptop_app)

    routes_client._TEST_TRANSPORT = httpx.ASGITransport(app=hub_app)
    yield hub_app, hub, laptop_app, laptop
    routes_client._TEST_TRANSPORT = None


def test_pair_upload_sync_roundtrip(hub_and_laptop, tmp_path, monkeypatch):
    hub_app, hub, laptop_app, laptop = hub_and_laptop

    # -- stub the hub's transcription dispatch: capture uploads instead
    #    of loading ML models.
    received = []

    def fake_run_transcribe_job(registry, job_id, audio_path, **kw):
        received.append(audio_path)

    from speechtotext.api import runner
    monkeypatch.setattr(runner, "run_transcribe_job", fake_run_transcribe_job)

    # -- 1. pair the laptop against the hub
    tok = hub.post("/pair/tokens").json()["token"]
    pairing = base64.b64encode(json.dumps({
        "hub_url": str(hub.base_url), "workspace_id": "ws-e2e",
        "token": tok,
    }).encode()).decode()
    resp = laptop.post("/client/hub/join", json={
        "pairing_string": pairing, "device_name": "e2e-laptop",
    })
    assert resp.status_code == 200, resp.text

    # -- 2. drop a file on the laptop → it must land in the outbox
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 128)
    resp = laptop.post("/jobs/transcribe", json={"path": str(audio)})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert laptop.get(f"/jobs/{job_id}").json()["kind"] == "hub_upload"

    # -- 3. drive one runtime cycle synchronously (no thread timing):
    #    sweep the outbox into the hub, then pull sync.
    rt = laptop_app.state.hub_runtime
    from speechtotext.client import identity, state, upload_queue, sync_puller
    from speechtotext.client.hub_client import HubClient
    from speechtotext.api import routes_client

    st = state.load()
    ident = identity.load()
    hub_client = HubClient(
        st.hub_url, st.device_id, ident.signing_key(),
        transport=routes_client._TEST_TRANSPORT,
    )
    sent = upload_queue.sweep(hub_client)
    assert len(sent) == 1
    assert received, "hub should have dispatched a transcription job"

    # -- 4. hub 'finishes' the job: write a transcript into the hub's
    #    incoming library dir and index it.
    out_dir = tmp_path / "hub-out"
    out_dir.mkdir()
    doc = out_dir / "meeting.json"
    doc.write_text(json.dumps({
        "audio_path": str(received[0]),
        "segments": [{"speaker": "SPEAKER_00", "text": "hoi wereld"}],
    }), encoding="utf-8")
    hub_app.state.library_dirs.add(out_dir)
    hub_app.state.library_db.sync_dirs([out_dir])

    # -- 5. laptop pulls sync → transcript appears in synced dir + index
    written = sync_puller.pull_once(hub_client)
    assert [p.name for p in written] == ["meeting.json"]
    laptop_app.state.library_dirs.add(written[0].parent)
    laptop_app.state.library_db.sync_dirs([written[0].parent])

    items = laptop.get("/transcripts?q=wereld").json()
    hits = items["items"] if isinstance(items, dict) else items
    assert any("meeting" in json.dumps(h) for h in hits)
    hub_client.close()
```

**Note to implementer:** adjust the final search-response unpacking to the real `GET /transcripts?q=` response shape in `speechtotext/api/routes_transcripts.py:90-103` before finalizing the assertion.

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/api/test_hub_client_e2e.py -v`
Expected: PASS. If it fails, this is integration fallout from Tasks 4-11 — debug with superpowers:systematic-debugging, do not weaken the test.

- [ ] **Step 3: Run the whole suite**

Run: `.venv/bin/python -m pytest tests -v --timeout=300 -x -q`
Expected: full suite green

- [ ] **Step 4: Commit**

```bash
git add tests/api/test_hub_client_e2e.py
git commit -m "test(api): end-to-end pair/upload/sync roundtrip for hub client mode"
```

---

### Task 14: Desktop UI — Join-hub settings card

**Files:**
- Modify: `ui/src/screens/SettingsScreen.tsx` (hub hosting card already lives here — add the client card below it)
- Create: `ui/src/lib/hubClient.ts`
- Test: `ui/src/lib/hubClient.test.ts`, extend `ui/src/screens/SettingsScreen.test.tsx`

- [ ] **Step 1: Write failing vitest for the API wrapper**

`ui/src/lib/hubClient.test.ts`:
```typescript
import { describe, expect, it, vi } from 'vitest';

import { hubStatus, joinHub, leaveHub } from './hubClient';

vi.mock('../api/client', () => ({
  api: vi.fn(),
}));

import { api } from '../api/client';

describe('hubClient', () => {
  it('hubStatus GETs /client/hub', async () => {
    (api as any).mockResolvedValue({ joined: false });
    expect(await hubStatus()).toEqual({ joined: false });
    expect(api).toHaveBeenCalledWith('/client/hub');
  });

  it('joinHub POSTs pairing string and device name', async () => {
    (api as any).mockResolvedValue({ joined: true, device_id: 'dev-1' });
    await joinHub('UGFpcg==', 'my-laptop');
    expect(api).toHaveBeenCalledWith('/client/hub/join', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pairing_string: 'UGFpcg==',
        device_name: 'my-laptop',
      }),
    });
  });

  it('leaveHub POSTs /client/hub/leave', async () => {
    (api as any).mockResolvedValue({ joined: false });
    await leaveHub();
    expect(api).toHaveBeenCalledWith('/client/hub/leave', { method: 'POST' });
  });
});
```

- [ ] **Step 2: Run, verify fail**

Run: `cd ui && npx vitest run src/lib/hubClient.test.ts`
Expected: FAIL — module not found

- [ ] **Step 3: Implement `ui/src/lib/hubClient.ts`**

```typescript
// Sidecar hub-client controls (join/leave/status). These talk to the
// LOCAL sidecar's loopback API, which in turn talks to the remote hub.
import { api } from '../api/client';

export interface HubClientStatus {
  joined: boolean;
  hub_url?: string;
  workspace_id?: string;
  device_id?: string;
  device_name?: string;
  cursor?: number;
  pending_uploads?: number;
  last_error?: string | null;
  last_sync_at?: number | null;
}

export async function hubStatus(): Promise<HubClientStatus> {
  return api<HubClientStatus>('/client/hub');
}

export async function joinHub(
  pairingString: string,
  deviceName: string,
): Promise<HubClientStatus> {
  return api<HubClientStatus>('/client/hub/join', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      pairing_string: pairingString,
      device_name: deviceName,
    }),
  });
}

export async function leaveHub(): Promise<HubClientStatus> {
  return api<HubClientStatus>('/client/hub/leave', { method: 'POST' });
}
```

- [ ] **Step 4: Run, verify pass**

Run: `cd ui && npx vitest run src/lib/hubClient.test.ts`
Expected: 3 passed

- [ ] **Step 5: Add the settings card**

In `ui/src/screens/SettingsScreen.tsx`, below the existing hub-hosting section, add a "Join a hub" card following the screen's existing card/state conventions (see the hub state handling at `SettingsScreen.tsx:104-170` for the established pattern):

```tsx
// State (top of component, near the existing hub state):
const [clientHub, setClientHub] = useState<HubClientStatus | null>(null);
const [pairingString, setPairingString] = useState('');
const [deviceName, setDeviceName] = useState('');
const [joinBusy, setJoinBusy] = useState(false);
const [joinError, setJoinError] = useState<string | null>(null);

useEffect(() => {
  hubStatus().then(setClientHub).catch(() => setClientHub(null));
}, []);

const doJoin = async () => {
  setJoinBusy(true);
  setJoinError(null);
  try {
    await joinHub(pairingString.trim(), deviceName.trim() || 'desktop');
    setClientHub(await hubStatus());
    setPairingString('');
  } catch (e) {
    setJoinError(`join failed: ${e}`);
  } finally {
    setJoinBusy(false);
  }
};

const doLeave = async () => {
  setJoinBusy(true);
  try {
    await leaveHub();
    setClientHub(await hubStatus());
  } finally {
    setJoinBusy(false);
  }
};
```

```tsx
{/* Card markup — match the surrounding section styling */}
<section>
  <h3>Join a hub</h3>
  {clientHub?.joined ? (
    <div>
      <p>
        Connected to <code>{clientHub.hub_url}</code> as{' '}
        <code>{clientHub.device_name}</code>
      </p>
      <p>
        {clientHub.pending_uploads
          ? `${clientHub.pending_uploads} recording(s) waiting for hub`
          : 'All uploads sent'}
        {clientHub.last_error ? ` — ${clientHub.last_error}` : ''}
      </p>
      <button onClick={doLeave} disabled={joinBusy}>
        Leave hub
      </button>
    </div>
  ) : (
    <div>
      <p>
        Paste a pairing code from the hub (run{' '}
        <code>locallexis-hub pair</code> on the server).
      </p>
      <input
        value={pairingString}
        onChange={(e) => setPairingString(e.target.value)}
        placeholder="pairing code"
      />
      <input
        value={deviceName}
        onChange={(e) => setDeviceName(e.target.value)}
        placeholder="device name (e.g. lieuwe-laptop)"
      />
      <button
        onClick={doJoin}
        disabled={joinBusy || !pairingString.trim()}
      >
        Join
      </button>
      {joinError && <p role="alert">{joinError}</p>}
    </div>
  )}
</section>
```

Extend `SettingsScreen.test.tsx` with one render test: mock `hubClient` module, assert the card renders the not-joined form, fire a join click, assert `joinHub` was called with the pasted string.

- [ ] **Step 6: Run UI tests + typecheck**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: all green

- [ ] **Step 7: Commit**

```bash
git add ui/src/lib/hubClient.ts ui/src/lib/hubClient.test.ts ui/src/screens/SettingsScreen.tsx ui/src/screens/SettingsScreen.test.tsx
git commit -m "feat(ui): join-hub settings card talking to sidecar client routes"
```

---

### Task 15: Desktop UI — origin badge + hub-upload job state

**Files:**
- Modify: `ui/src/screens/LibraryScreen.tsx`, `ui/src/stores/library.ts` (surface `origin` from the API rows)
- Modify: `ui/src/screens/IdleScreen.tsx` (job kind `hub_upload` → "Sent to hub for processing" state instead of the local progress flow)
- Test: extend existing screen tests

- [ ] **Step 1: Surface `origin` in the library store**

In `ui/src/stores/library.ts`, add `origin?: 'local' | 'hub'` to the library item interface (the API now returns it per Task 9).

- [ ] **Step 2: Badge in `LibraryScreen.tsx`**

Where each row renders its metadata, add:
```tsx
{item.origin === 'hub' && (
  <span className="origin-badge" title="Synced from hub">hub</span>
)}
```
Style `.origin-badge` consistently with existing chips in the screen's stylesheet (small, muted, uppercase).

- [ ] **Step 3: Hub-upload job state in `IdleScreen.tsx`**

Where the screen branches on job kind/status after a drop (find the `job.kind === 'transcribe'` handling), add the `hub_upload` case: while `status === 'pending'` show "Queued for hub…", on `status === 'complete'` with `stage === 'sent-to-hub'` show "Sent to hub — the transcript will appear in your library when processed." and return to idle. No local progress bar (there are no local stages).

- [ ] **Step 4: Extend tests**

- Library test: render a row with `origin: 'hub'`, assert the badge text.
- Idle test: mock a `hub_upload` job reaching `sent-to-hub`, assert the message renders.

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: green

- [ ] **Step 5: Commit**

```bash
git add ui/src
git commit -m "feat(ui): hub origin badge and sent-to-hub job state"
```

---

### Task 16: Version bump + wrap-up

**Files:**
- Modify: `pyproject.toml:7` (version)

- [ ] **Step 1: Full test sweep**

Run: `.venv/bin/python -m pytest tests -q` and `cd ui && npx vitest run && npx tsc --noEmit`
Expected: everything green

- [ ] **Step 2: Bump version**

`pyproject.toml`: `version = "0.9.9"` → `version = "0.10.0"` (new feature ⇒ minor bump).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: bump version to 0.10.0"
```

- [ ] **Step 4: Manual device-test checklist (batched session, per workflow convention)**

Not automatable — record for the user's next hardware session:
1. Server: enable headless hub mode with API token, run `locallexis-hub pair --url http://<tailnet-name>:8010`.
2. Laptop: paste pairing string in Settings → Join. Verify status card shows connected.
3. Drop a file on the laptop → verify "Sent to hub", transcript appears in library with `hub` badge within a sync cycle after the server finishes processing.
4. Kill the network mid-upload → verify "N waiting for hub", restore network, verify drain.
5. Relabel a hub transcript on the laptop → verify the new name shows on the phone after its next sync.
6. Leave hub → verify synced transcripts remain searchable.
