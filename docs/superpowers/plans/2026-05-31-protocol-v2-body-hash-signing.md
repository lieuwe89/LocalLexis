# Protocol v2: Body-Hash Signing + Streaming Upload — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move device-signed requests from "sign raw body" to "sign sha256(body)" and stream large uploads through hub + firmware so one-hour meeting recordings (~115 MiB) fit in ESP32 RAM.

**Architecture:** Three implementations (firmware C++, hub Python, Android Kotlin) all replace the v1 signed message `METHOD\nTARGET\nTS\nNONCE\nBODY` with v2 `locallexis-sig-v2\nMETHOD\nTARGET\nTS\nNONCE\nSHA256(BODY)`. Firmware gains a `BodySource` abstraction plus a hash-then-stream uploader. Hub `/jobs/upload` switches from `await request.body()` to `request.stream()` with tee-to-temp-file. Hard cut — v1 deleted in the same change. Android signing changes form but keeps buffering (streaming Android deferred).

**Tech Stack:** C++17 (firmware, mbedtls + rweather/Crypto for Ed25519), Python 3.11 (hub, FastAPI + PyNaCl), Kotlin (Android, lazysodium-android via OkHttp interceptor).

**Reference spec:** `docs/superpowers/specs/2026-05-30-protocol-v2-body-hash-signing-design.md`

**Section 10 resolutions:**

1. **Host-test build**: Add `firmware/esp32-recorder/test/host/Makefile` that builds each test with plain `g++ -std=c++17 -I../../src` against pure-C++ source files only. No `[env:native]` in `platformio.ini`. Existing `test_provisioning_protocol.cpp` and `test_hub_url.cpp` are picked up by the same Makefile.
2. **FileLike seam**: 3-method interface — `size_t size() const`, `bool seekToStart()`, `size_t read(uint8_t*, size_t)`. Pure C++ abstract in `src/storage/FileLike.h`. Arduino impl `SdFile` wraps `SD_MMC` `File` (never compiled on host). `SdFileBodySource` depends on `FileLike` only → host-testable with a `FakeFileLike`.
3. **Hub incoming-dir scratch**: `app.py` already sets `app.state.incoming_dir`, and `_write_atomic` already creates `incoming.parent`. `.partial` files go in the same dir as the final dest. Startup hook iterates `incoming_dir.glob("*.partial")` and unlinks.
4. **mbedtls SHA-256 streaming API**: Existing `SignedHttpClient.cpp` calls `mbedtls_sha256_ret(...)`, so the `_ret`-suffixed family is present on the pinned arduino-esp32 core. Use the triplet `mbedtls_sha256_starts_ret`, `mbedtls_sha256_update_ret`, `mbedtls_sha256_finish_ret`.

**Golden vector** (used in three tests for byte-exact cross-language verification):

| Input | Value |
|---|---|
| Ed25519 seed | `000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f` |
| Pubkey (raw, hex) | `03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8` |
| Pubkey (base64) | `A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg=` |
| method | `POST` |
| target | `/jobs/upload?filename=t.wav` |
| timestamp | `1700000000` |
| nonce | `abc123` |
| body | `hello` (5 ASCII bytes) |
| `sha256(body)` (hex) | `2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824` |
| signed message length | 101 bytes |
| signed message (hex) | `6c6f63616c6c657869732d7369672d76320a504f53540a2f6a6f62732f75706c6f61643f66696c656e616d653d742e7761760a313730303030303030300a6162633132330a2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824` |
| signature (hex) | `fceb1fb0c3cb8605e813ef62cf32a6c57ab624d72e1a152ee856c5db75a73d87ea25089e42b60c4dcf006c36be8398ff5a89cc889a6f429b29154f036e0a5903` |
| signature (base64) | `/OsfsMPLhgXoE+9izzKmxXq2JNcuGhUu6FbF23WnPYfqJQieQrYMTc8AbDa+g5j/WonMiJpvQpspFU8DbgpZAw==` |
| `sha256(b"")` (hex) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

Firmware host test asserts byte-equality of the constructed message only (no Ed25519 on host). Hub + Android tests assert both message bytes AND the base64 signature.

---

## File Structure

**Create:**
- `firmware/esp32-recorder/src/crypto/SignedMessage.h` — pure-C++ v2 message builder
- `firmware/esp32-recorder/src/crypto/SignedMessage.cpp`
- `firmware/esp32-recorder/src/net/BodySource.h` — pure-C++ abstract interface
- `firmware/esp32-recorder/src/net/VectorBodySource.h`
- `firmware/esp32-recorder/src/net/VectorBodySource.cpp`
- `firmware/esp32-recorder/src/storage/FileLike.h` — pure-C++ abstract for SD or fake
- `firmware/esp32-recorder/src/storage/SdFile.h` — Arduino impl (wraps `SD_MMC` `File`)
- `firmware/esp32-recorder/src/storage/SdFile.cpp`
- `firmware/esp32-recorder/src/storage/SdFileBodySource.h` — pure-C++ (depends on FileLike)
- `firmware/esp32-recorder/src/storage/SdFileBodySource.cpp`
- `firmware/esp32-recorder/test/host/Makefile`
- `firmware/esp32-recorder/test/host/test_sign_v2.cpp`
- `firmware/esp32-recorder/test/host/test_body_source.cpp`
- `tests/api/test_auth_v2.py` — golden-vector + v1-rejection
- `tests/api/test_routes_ingest_v2.py` — streaming-path scenarios

**Modify:**
- `firmware/esp32-recorder/src/crypto/DeviceCrypto.h` / `.cpp` — add `signRequestB64WithBodyDigest`; existing `signRequestB64` becomes thin wrapper
- `firmware/esp32-recorder/src/net/SignedHttpClient.h` / `.cpp` — new `uploadWav(BodySource&)` overload; vector overload becomes wrapper
- `firmware/esp32-recorder/src/storage/SdQueue.h` / `.cpp` — add `peekOldestPath`, `openReader`; delete `peekOldest`
- `firmware/esp32-recorder/src/main.cpp` — `drainQueueStep` uses streaming reader
- `firmware/esp32-recorder/platformio.ini` — add `-DLOCALLEXIS_PROTO_VERSION=2`
- `firmware/esp32-recorder/README.md` — protocol version + limits
- `speechtotext/api/auth.py` — `build_signed_message` takes `body_sha256`; add `verify_device_signature_with_digest`; docstring v1→v2
- `speechtotext/api/routes_ingest.py` — inline streaming `/jobs/upload`; delete `verify_upload_signature`
- `speechtotext/api/app.py` — startup `.partial` sweep
- `tests/api/_signing.py` — internally hash body, keep external signature
- `tests/api/test_routes_ingest.py` — existing scenarios still pass (signed_headers helper adapts)
- `android/app/src/main/kotlin/app/locallexis/data/crypto/CryptoBox.kt` — v2 `buildRequestMessage`; kdoc
- `android/app/src/test/kotlin/app/locallexis/data/crypto/CryptoBoxTest.kt` — v2 expectations + golden vector
- `android/app/src/test/kotlin/app/locallexis/data/pairing/SignedRequestInterceptorTest.kt` — v2 expectations
- `pyproject.toml` — `0.9.4` → `0.9.5`
- `android/app/build.gradle.kts` — versionName `0.9.4` → `0.9.5`, versionCode `7` → `8`
- `ui/package.json` — `0.9.4` → `0.9.5`
- `ui/src-tauri/Cargo.toml` — `0.9.3` → `0.9.5`
- `ui/src-tauri/tauri.conf.json` — `0.9.3` → `0.9.5`

**Delete (function-level):**
- `SdQueue::peekOldest` (declaration + definition)
- `routes_ingest.verify_upload_signature` (no remaining callers)

---

## Build Sequence Rationale

1. **Hub v2 crypto first.** Pure protocol change; existing tests prove no behavior regression beyond the byte format. Bootstrap of golden vector.
2. **Hub `/jobs/upload` streaming.** Independent of v2 message change (could land alone), but bundled per spec.
3. **Firmware pure-C++ pieces** (`SignedMessage`, `BodySource`, `VectorBodySource`, `SdFileBodySource`) — host-tested before any Arduino code touches them.
4. **Firmware Arduino glue** (`DeviceCrypto`, `SignedHttpClient`, `SdQueue`, `main.cpp`) — build-verified via `pio run`, runtime-verified later on hardware.
5. **Android v2** — independent of firmware/hub commit order since tests are self-contained.
6. **Version bumps + docs** — last, single commit.

Each commit is atomic and keeps **its own language's** test suite green. Cross-language inconsistency exists transiently between commits — acceptable because deploy is coordinated per Section 9 of the spec.

---

## Task 1: Hub — v2 signed message + verify-with-digest helper

**Files:**
- Modify: `speechtotext/api/auth.py`
- Modify: `tests/api/_signing.py`
- Create: `tests/api/test_auth_v2.py`

- [ ] **Step 1: Update `_signing.py` helper to hash body internally**

The helper's callers pass raw `body` — keep that external API, hash inside.

Replace the body of `signed_headers` in [tests/api/_signing.py](tests/api/_signing.py:17):

```python
def signed_headers(
    sk,
    device_id: str,
    method: str,
    path: str,
    body: bytes | str = b"",
    *,
    timestamp: int | float | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """Return X-Device-Id/Signature/Timestamp/Nonce headers for a request.

    ``path`` may include a ``?query`` — it is split and folded into the
    signed message exactly as the server reconstructs it from the URL.
    """
    import hashlib

    raw_body = body if isinstance(body, (bytes, bytearray)) else body.encode("utf-8")
    ts = str(int(time.time())) if timestamp is None else str(timestamp)
    nc = secrets.token_hex(8) if nonce is None else nonce
    p, _, q = path.partition("?")
    body_sha256 = hashlib.sha256(raw_body).digest()
    msg = build_signed_message(method, p, q, ts, nc, body_sha256)
    sig = sk.sign(msg).signature
    return {
        "X-Device-Id": device_id,
        "X-Signature-B64": base64.b64encode(sig).decode("ascii"),
        "X-Timestamp": ts,
        "X-Nonce": nc,
    }
```

- [ ] **Step 2: Update `build_signed_message` to v2 form**

Replace the function in [speechtotext/api/auth.py:62-81](speechtotext/api/auth.py:62):

```python
def build_signed_message(
    method: str,
    path: str,
    query: str,
    timestamp: str,
    nonce: str,
    body_sha256: bytes,
) -> bytes:
    """Canonical v2 bytes a device signs and the hub verifies.

    Layout::

        locallexis-sig-v2\\nMETHOD\\nTARGET\\nTIMESTAMP\\nNONCE\\nSHA256(BODY)

    TARGET is ``path`` plus ``?query`` when a query string is present. The
    body digest (32 raw bytes, not hex) lets the signature stay one-shot
    over a fixed ~90-byte message even when the body is gigabytes. The
    domain tag pins the protocol version inside the signed bytes so it
    cannot be downgraded by header tampering.
    """
    if len(body_sha256) != 32:
        raise ValueError(
            f"body_sha256 must be 32 bytes, got {len(body_sha256)}"
        )
    target = path if not query else f"{path}?{query}"
    return b"\n".join(
        (
            b"locallexis-sig-v2",
            method.encode("ascii"),
            target.encode("ascii"),
            timestamp.encode("ascii"),
            nonce.encode("ascii"),
            body_sha256,
        )
    )
```

- [ ] **Step 3: Add `verify_device_signature_with_digest` helper, make `verify_device_signature` a wrapper**

In [speechtotext/api/auth.py](speechtotext/api/auth.py), replace the entire `verify_device_signature` function (lines 112-200) with:

```python
async def verify_device_signature_with_digest(
    request: Request, body_sha256: bytes
) -> str:
    """Verify the v2 signature given a precomputed body digest.

    Shared verification core used by:
    - small-body endpoints via :func:`verify_device_signature` (which
      reads the body and hashes it for the caller);
    - the streaming ``/jobs/upload`` route, which hashes the body in a
      single pass and calls this helper directly so the full body is
      never resident.

    Returns the verified ``device_id``; raises ``HTTPException(401)`` on
    any failure (missing header, stale timestamp, unknown device, bad
    signature, replayed nonce).
    """
    from nacl.exceptions import BadSignatureError
    from nacl.signing import VerifyKey

    device_id = request.headers.get("X-Device-Id")
    sig_b64 = request.headers.get("X-Signature-B64")
    timestamp = request.headers.get("X-Timestamp")
    nonce = request.headers.get("X-Nonce")
    if not device_id or not sig_b64 or not timestamp or not nonce:
        raise HTTPException(
            status_code=401,
            detail="missing X-Device-Id / X-Signature-B64 / X-Timestamp / X-Nonce header",
        )

    try:
        ts = float(timestamp)
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid X-Timestamp")
    if abs(time.time() - ts) > _SIGNATURE_WINDOW_S:
        raise HTTPException(
            status_code=401, detail="stale request (timestamp outside window)"
        )

    registry = getattr(request.app.state, "device_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=500, detail="device registry not configured"
        )
    record = registry.get(device_id)
    if record is None:
        raise HTTPException(status_code=401, detail="unknown device")

    try:
        signature = base64.b64decode(sig_b64, validate=True)
        pubkey_raw = base64.b64decode(record["pubkey_b64"], validate=True)
    except Exception:
        raise HTTPException(status_code=401, detail="bad signature encoding")

    message = build_signed_message(
        request.method,
        request.url.path,
        request.url.query,
        timestamp,
        nonce,
        body_sha256,
    )

    try:
        VerifyKey(pubkey_raw).verify(message, signature)
    except BadSignatureError:
        raise HTTPException(
            status_code=401, detail="signature verification failed"
        )
    except Exception as exc:
        raise HTTPException(
            status_code=401, detail=f"signature check error: {exc}"
        )

    nonce_cache = getattr(request.app.state, "nonce_cache", None)
    if nonce_cache is not None and not nonce_cache.check_and_store(device_id, nonce):
        raise HTTPException(
            status_code=401, detail="replay detected (nonce reused)"
        )

    registry.update_last_seen(device_id)
    request.state.device_id = device_id
    return device_id


async def verify_device_signature(request: Request) -> str:
    """FastAPI dependency. Reads the request body, hashes it, verifies.

    Use for small-body endpoints (``/sync/*``, ``PATCH /transcripts/{tid}``).
    Endpoints that need streaming (``/jobs/upload``) should hash the body
    in their own loop and call :func:`verify_device_signature_with_digest`.
    """
    import hashlib

    body = await request.body()
    body_sha256 = hashlib.sha256(body).digest()
    return await verify_device_signature_with_digest(request, body_sha256)
```

- [ ] **Step 4: Replace the auth.py module docstring**

Replace lines 1-46 of [speechtotext/api/auth.py](speechtotext/api/auth.py:1) with:

```python
"""Device-signed request verification.

Wire protocol (v2)
------------------

Each request from a paired device carries four headers::

    X-Device-Id:     dev-<hex>
    X-Signature-B64: base64(Ed25519 signature)
    X-Timestamp:     unix seconds (string)
    X-Nonce:         random per-request token

The signature is computed over the message::

    "locallexis-sig-v2" + "\\n"
        + HTTP_METHOD + "\\n"
        + PATH ["?" QUERY] + "\\n"
        + X-Timestamp + "\\n"
        + X-Nonce + "\\n"
        + sha256(raw_body_bytes)        # 32 raw digest bytes, not hex

with the device's Ed25519 signing key (see :func:`build_signed_message`).
The hub looks the device up by id, fetches the stored verify key,
rebuilds the same message, and calls :meth:`nacl.signing.VerifyKey.verify`.

The domain tag ``locallexis-sig-v2`` pins the protocol version *inside*
the signed bytes, so a man-in-the-middle cannot strip or downgrade it.
The body is signed as a fixed-size SHA-256 digest, which keeps the
signed message ~90 bytes regardless of body size — meeting-length
audio uploads stream through a single hashing pass.

Replay protection: the timestamp must be within ``_SIGNATURE_WINDOW_S``
of the hub clock, and the ``(device_id, nonce)`` pair must be unseen
within that window (tracked by :class:`NonceCache`). The query string
is part of the signed bytes, so a captured request cannot be replayed
nor have its path/query parameters tampered with.

Failure modes
-------------

- Missing ``X-Device-Id`` / ``X-Signature-B64`` / ``X-Timestamp`` /
  ``X-Nonce``: 401 + structured detail.
- Timestamp outside the allowed window: 401 ``stale request``.
- Device id not in registry: 401 ``unknown device``.
- Signature does not verify (bad sig OR tampered body → digest mismatch):
  401 ``signature verification failed``.
- ``(device_id, nonce)`` already seen this window: 401 ``replay detected``.

Side effects on success
-----------------------

- ``DeviceRegistry.update_last_seen`` is called.
- ``request.state.device_id`` is populated for downstream handlers.
"""
```

- [ ] **Step 5: Run existing hub auth tests — confirm still green**

```bash
.venv/bin/pytest tests/api/test_auth.py tests/api/test_routes_sync.py tests/api/test_routes_transcripts.py -v
```

Expected: all PASS. The `signed_headers` helper now produces v2 headers; the new `verify_device_signature` hashes-then-verifies; tests assert behavior, not byte format, so they should be unaffected.

If any test fails: do **not** mutate the test to "match" — investigate first. The only legitimate change to existing tests is updating any test that hardcoded the v1 byte layout (none expected based on the audit).

- [ ] **Step 6: Add `test_auth_v2.py` golden vector + tamper test**

Create [tests/api/test_auth_v2.py](tests/api/test_auth_v2.py):

```python
"""Protocol v2: byte-exact golden-vector tests for build_signed_message
and end-to-end verify of a tampered body."""

from __future__ import annotations

import base64
import hashlib

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from speechtotext.api.app import create_app
from speechtotext.api.auth import build_signed_message
from tests.api._signing import signed_headers


GOLDEN_SEED = bytes(range(32))
GOLDEN_PUBKEY_B64 = "A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg="
GOLDEN_METHOD = "POST"
GOLDEN_TARGET = "/jobs/upload?filename=t.wav"
GOLDEN_PATH = "/jobs/upload"
GOLDEN_QUERY = "filename=t.wav"
GOLDEN_TS = "1700000000"
GOLDEN_NONCE = "abc123"
GOLDEN_BODY = b"hello"
GOLDEN_BODY_SHA256_HEX = (
    "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
)
GOLDEN_MSG_HEX = (
    "6c6f63616c6c657869732d7369672d76320a504f53540a2f6a6f62732f75706c"
    "6f61643f66696c656e616d653d742e7761760a313730303030303030300a6162"
    "633132330a2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e730433"
    "62938b9824"
)
GOLDEN_SIG_B64 = (
    "/OsfsMPLhgXoE+9izzKmxXq2JNcuGhUu6FbF23WnPYfqJQieQrYMTc8AbDa+g5j/"
    "WonMiJpvQpspFU8DbgpZAw=="
)


def test_build_signed_message_golden_vector_bytes():
    digest = hashlib.sha256(GOLDEN_BODY).digest()
    assert digest.hex() == GOLDEN_BODY_SHA256_HEX

    msg = build_signed_message(
        GOLDEN_METHOD,
        GOLDEN_PATH,
        GOLDEN_QUERY,
        GOLDEN_TS,
        GOLDEN_NONCE,
        digest,
    )
    assert msg.hex() == GOLDEN_MSG_HEX
    assert len(msg) == 101


def test_build_signed_message_golden_vector_signature():
    sk = SigningKey(GOLDEN_SEED)
    assert base64.b64encode(bytes(sk.verify_key)).decode() == GOLDEN_PUBKEY_B64

    digest = hashlib.sha256(GOLDEN_BODY).digest()
    msg = build_signed_message(
        GOLDEN_METHOD,
        GOLDEN_PATH,
        GOLDEN_QUERY,
        GOLDEN_TS,
        GOLDEN_NONCE,
        digest,
    )
    sig = sk.sign(msg).signature
    assert base64.b64encode(sig).decode() == GOLDEN_SIG_B64


def test_build_signed_message_empty_body_uses_well_known_digest():
    empty_digest = hashlib.sha256(b"").digest()
    assert (
        empty_digest.hex()
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    msg = build_signed_message("GET", "/sync/snapshot", "", "ts", "n", empty_digest)
    expected_prefix = b"locallexis-sig-v2\nGET\n/sync/snapshot\nts\nn\n"
    assert msg.startswith(expected_prefix)
    assert msg[len(expected_prefix):] == empty_digest


def test_build_signed_message_rejects_wrong_digest_length():
    with pytest.raises(ValueError, match="32 bytes"):
        build_signed_message("GET", "/", "", "ts", "n", b"too short")


def test_tampered_body_fails_verification(tmp_path, monkeypatch):
    """A captured request with the body altered must 401 on verify."""
    app = create_app(
        library_db_path=tmp_path / "library.db",
        devices_db_path=tmp_path / "devices.db",
    )
    monkeypatch.setattr(
        "speechtotext.api.runner.run_transcribe_job", lambda *a, **k: None
    )
    sk = SigningKey.generate()
    device_id = "dev-tamper"
    app.state.device_registry.register(
        device_id=device_id,
        pubkey_b64=base64.b64encode(bytes(sk.verify_key)).decode("ascii"),
        name="ESP32",
    )
    client = TestClient(app)
    path = "/jobs/upload?filename=ok.wav"
    body = b"RIFF\x24\x00\x00\x00WAVEfmt "

    headers = signed_headers(sk, device_id, "POST", path, body)
    tampered_body = body + b"\x00"  # one extra byte
    r = client.post(path, content=tampered_body, headers=headers)
    assert r.status_code == 401
    assert r.json()["detail"] == "signature verification failed"
```

- [ ] **Step 7: Run new v2 test file**

```bash
.venv/bin/pytest tests/api/test_auth_v2.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 8: Commit**

```bash
git add speechtotext/api/auth.py tests/api/_signing.py tests/api/test_auth_v2.py
git commit -m "$(cat <<'EOF'
feat(hub): protocol v2 sign sha256(body) with locallexis-sig-v2 domain tag

build_signed_message now takes a 32-byte body digest instead of the raw
body, letting Ed25519 stay one-shot over a ~90-byte message regardless
of body size. Adds verify_device_signature_with_digest for streaming
endpoints; verify_device_signature becomes a thin wrapper that hashes
the body for small-body callers. Hard cut — v1 layout deleted.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Hub — streaming `/jobs/upload` + orphan `.partial` sweep

**Files:**
- Modify: `speechtotext/api/routes_ingest.py`
- Modify: `speechtotext/api/app.py`
- Modify: `tests/api/test_routes_ingest.py`
- Create: `tests/api/test_routes_ingest_v2.py`

- [ ] **Step 1: Inline streaming verify in `post_upload`, delete `verify_upload_signature`**

Replace [speechtotext/api/routes_ingest.py](speechtotext/api/routes_ingest.py) entirely with:

```python
"""Audio ingest endpoints for paired LAN devices.

``/jobs/upload`` accepts a complete signed audio file. The body is
streamed through a single SHA-256 + tee-to-temp-file pass so meeting-
length recordings do not need to be buffered in RAM, then the device
signature is verified against the computed digest. On verify failure
the temp file is deleted; on success it is renamed into place and a
transcription job is dispatched.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from speechtotext.api import library_db as library_db_module
from speechtotext.api.auth import verify_device_signature_with_digest

router = APIRouter()
DEFAULT_MAX_UPLOAD_BYTES = 256 * 1024 * 1024
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,179}$")


class UploadResponse(BaseModel):
    job_id: str
    bytes_received: int = Field(ge=1)


def _incoming_dir(request: Request) -> Path:
    configured = getattr(request.app.state, "incoming_dir", None)
    if configured is not None:
        return Path(configured)
    return library_db_module.default_app_data_dir() / "incoming"


def _safe_filename(filename: str | None) -> str:
    if filename is None or not filename.strip():
        return "upload.wav"
    name = filename.strip()
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise HTTPException(
            status_code=400, detail="filename must be a simple basename"
        )
    if not _SAFE_FILENAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=400,
            detail=(
                "filename must contain only letters, numbers, dot, dash, "
                "or underscore"
            ),
        )
    return name


def _unique_upload_path(root: Path, filename: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    suffix = secrets.token_hex(4)
    return root / f"{stamp}-{suffix}-{filename}"


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def sweep_partial_uploads(incoming_dir: Path) -> int:
    """Delete any leftover ``*.partial`` files under ``incoming_dir``.

    Called at app startup so a crash mid-stream cannot leave indefinite
    scratch files behind.
    """
    if not incoming_dir.exists():
        return 0
    removed = 0
    for partial in incoming_dir.glob("*.partial"):
        try:
            partial.unlink()
            removed += 1
        except OSError:
            pass
    return removed


@router.post("/jobs/upload", status_code=202, response_model=UploadResponse)
async def post_upload(
    request: Request,
    filename: str | None = Query(default=None, max_length=180),
) -> UploadResponse:
    """Accept a streaming signed audio upload, verify, dispatch transcription.

    Flow:
      1. Cheap header checks (Content-Length present + within limit).
      2. Stream body through SHA-256 + tee to ``<incoming>/<random>.partial``,
         capping at ``max_upload_bytes``.
      3. Verify signature against the computed digest. On failure delete
         temp + raise 401.
      4. ``os.replace`` temp → final dest. Dispatch transcription.
    """
    max_bytes = int(
        getattr(request.app.state, "max_upload_bytes", DEFAULT_MAX_UPLOAD_BYTES)
    )
    raw_length = request.headers.get("content-length")
    if raw_length is None:
        raise HTTPException(status_code=411, detail="Content-Length required")
    try:
        content_length = int(raw_length)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="invalid Content-Length"
        ) from exc
    if content_length > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"audio upload exceeds {max_bytes} byte limit",
        )

    safe_name = _safe_filename(filename)
    incoming = _incoming_dir(request)
    incoming.mkdir(parents=True, exist_ok=True)
    temp_path = incoming / f"{secrets.token_hex(8)}.partial"

    hasher = hashlib.sha256()
    bytes_seen = 0
    try:
        with temp_path.open("wb") as fh:
            async for chunk in request.stream():
                if not chunk:
                    continue
                bytes_seen += len(chunk)
                if bytes_seen > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"audio upload exceeds {max_bytes} byte limit",
                    )
                hasher.update(chunk)
                fh.write(chunk)
    except HTTPException:
        _unlink_quietly(temp_path)
        raise
    except Exception:
        _unlink_quietly(temp_path)
        raise

    if bytes_seen == 0:
        _unlink_quietly(temp_path)
        raise HTTPException(
            status_code=400, detail="audio upload body cannot be empty"
        )

    try:
        device_id = await verify_device_signature_with_digest(
            request, hasher.digest()
        )
    except HTTPException:
        _unlink_quietly(temp_path)
        raise
    _ = device_id  # reserved for future per-device routing

    audio_path = _unique_upload_path(incoming, safe_name)
    try:
        os.replace(temp_path, audio_path)
    except OSError as exc:
        _unlink_quietly(temp_path)
        raise HTTPException(
            status_code=500, detail=f"failed to store upload: {exc}"
        ) from exc

    registry = request.app.state.jobs
    job_id = registry.create(kind="transcribe", audio_path=str(audio_path))

    from speechtotext.api import runner

    try:
        runner.run_transcribe_job(registry, job_id, audio_path)
    except Exception as exc:
        _unlink_quietly(audio_path)
        raise HTTPException(
            status_code=500,
            detail=(
                "failed to dispatch upload job: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc

    return UploadResponse(job_id=job_id, bytes_received=bytes_seen)
```

- [ ] **Step 2: Add startup `.partial` sweep in app.py**

In [speechtotext/api/app.py](speechtotext/api/app.py), update the import block — replace the existing `from speechtotext.api.routes_ingest import (...)` line:

```python
from speechtotext.api.routes_ingest import (
    DEFAULT_MAX_UPLOAD_BYTES,
    router as ingest_router,
    sweep_partial_uploads,
)
```

Then inside `_on_startup` at [speechtotext/api/app.py:196](speechtotext/api/app.py:196), append the sweep call. Replace the function body with:

```python
    @app.on_event("startup")
    def _on_startup() -> None:
        # Trigger the macOS mic permission prompt at app launch instead of
        # when the user clicks Record, so the first recording isn't missing
        # its opening seconds while the user is dismissing a dialog.
        warm_microphone_in_background()
        # Reconcile the library index with what is actually on disk. Runs
        # in a background thread so a large library does not delay /health.
        threading.Thread(
            target=app.state.library_db.sync_dirs,
            args=(list(app.state.library_dirs),),
            daemon=True,
        ).start()
        # Streaming /jobs/upload writes a <random>.partial scratch file
        # while it hashes; a crash mid-stream would leak it indefinitely.
        removed = sweep_partial_uploads(Path(app.state.incoming_dir))
        if removed:
            import logging

            logging.getLogger("speechtotext.api").info(
                "swept %d orphan partial upload(s) at startup", removed
            )
```

- [ ] **Step 3: Run existing ingest tests — confirm all still green**

```bash
.venv/bin/pytest tests/api/test_routes_ingest.py -v
```

Expected: 5 tests PASS (whole-file upload, dispatch-fail cleans audio, empty-body reject, oversize reject, bad-filename reject). The Content-Length oversize test still hits the pre-stream guard; the dispatch-fail test still finds the audio in the incoming dir after `os.replace`; the empty-body test now triggers post-stream.

If `test_upload_cleans_saved_audio_when_dispatch_fails` fails: the new code deletes the audio after `runner.run_transcribe_job` raises (same behavior as v1, line 132). Re-read the test if anything differs.

- [ ] **Step 4: Write `test_routes_ingest_v2.py` for streaming-specific scenarios**

Create [tests/api/test_routes_ingest_v2.py](tests/api/test_routes_ingest_v2.py):

```python
"""Streaming /jobs/upload scenarios: oversize mid-stream, bad signature
post-stream, replay nonce post-stream, orphan .partial sweep at startup."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from speechtotext.api.app import create_app
from speechtotext.api.routes_ingest import sweep_partial_uploads
from tests.api._signing import signed_headers


def _register_device(app) -> tuple[SigningKey, str]:
    sk = SigningKey.generate()
    device_id = "dev-stream"
    app.state.device_registry.register(
        device_id=device_id,
        pubkey_b64=base64.b64encode(bytes(sk.verify_key)).decode("ascii"),
        name="ESP32",
    )
    return sk, device_id


def _make_app(tmp_path, monkeypatch):
    app = create_app(
        library_db_path=tmp_path / "library.db",
        devices_db_path=tmp_path / "devices.db",
    )
    monkeypatch.setattr(
        "speechtotext.api.runner.run_transcribe_job", MagicMock()
    )
    return app


def test_signature_failure_deletes_partial(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    sk, device_id = _register_device(app)
    client = TestClient(app)
    path = "/jobs/upload?filename=sig-fails.wav"
    body = b"RIFF\x24\x00\x00\x00WAVEfmt "

    headers = signed_headers(sk, device_id, "POST", path, body)
    headers["X-Signature-B64"] = base64.b64encode(b"\x00" * 64).decode()

    r = client.post(path, content=body, headers=headers)
    assert r.status_code == 401

    incoming = Path(app.state.incoming_dir)
    leftovers = list(incoming.glob("*.partial")) if incoming.exists() else []
    assert leftovers == []
    # And no audio either — verify rejection means no rename happened.
    audio = list(incoming.glob("*sig-fails.wav")) if incoming.exists() else []
    assert audio == []


def test_replay_nonce_deletes_partial(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    sk, device_id = _register_device(app)
    client = TestClient(app)
    path = "/jobs/upload?filename=replay.wav"
    body = b"audio"

    # First upload — succeeds, consumes the nonce.
    first = signed_headers(
        sk, device_id, "POST", path, body, nonce="fixed-nonce-1"
    )
    r1 = client.post(path, content=body, headers=first)
    assert r1.status_code == 202, r1.text

    # Same nonce — verify-fail post-stream. Temp must be cleaned.
    second = signed_headers(
        sk, device_id, "POST", path, body, nonce="fixed-nonce-1"
    )
    r2 = client.post(path, content=body, headers=second)
    assert r2.status_code == 401
    assert "replay" in r2.json()["detail"]

    incoming = Path(app.state.incoming_dir)
    leftovers = list(incoming.glob("*.partial"))
    assert leftovers == []


def test_oversize_via_content_length_rejects_pre_stream(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app.state.max_upload_bytes = 4
    sk, device_id = _register_device(app)
    client = TestClient(app)
    path = "/jobs/upload?filename=big.wav"
    body = b"too long for limit"

    r = client.post(
        path, content=body, headers=signed_headers(sk, device_id, "POST", path, body)
    )
    assert r.status_code == 413

    incoming = Path(app.state.incoming_dir)
    leftovers = list(incoming.glob("*.partial")) if incoming.exists() else []
    assert leftovers == []


def test_sweep_partial_uploads_removes_orphans(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "abc.partial").write_bytes(b"x")
    (incoming / "def.partial").write_bytes(b"y")
    (incoming / "keep.wav").write_bytes(b"z")

    removed = sweep_partial_uploads(incoming)

    assert removed == 2
    assert (incoming / "keep.wav").exists()
    assert not any(incoming.glob("*.partial"))


def test_sweep_partial_uploads_handles_missing_dir(tmp_path):
    removed = sweep_partial_uploads(tmp_path / "does-not-exist")
    assert removed == 0
```

- [ ] **Step 5: Run new streaming tests + full ingest suite**

```bash
.venv/bin/pytest tests/api/test_routes_ingest.py tests/api/test_routes_ingest_v2.py -v
```

Expected: 10 tests PASS total.

- [ ] **Step 6: Commit**

```bash
git add speechtotext/api/routes_ingest.py speechtotext/api/app.py tests/api/test_routes_ingest_v2.py
git commit -m "$(cat <<'EOF'
feat(hub): stream /jobs/upload through sha256 + tee instead of buffering

Body is streamed to a <random>.partial scratch file while SHA-256 is
computed incrementally; the digest is then handed to
verify_device_signature_with_digest. On signature failure the temp is
deleted; on success it is os.replace'd to the final dest. A startup
hook sweeps any .partial files left by a crashed prior run. Removes the
old verify_upload_signature wrapper and its await request.body() path.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Firmware host-test runner + pure-C++ `SignedMessage`

**Files:**
- Create: `firmware/esp32-recorder/src/crypto/SignedMessage.h`
- Create: `firmware/esp32-recorder/src/crypto/SignedMessage.cpp`
- Create: `firmware/esp32-recorder/test/host/Makefile`
- Create: `firmware/esp32-recorder/test/host/test_sign_v2.cpp`

- [ ] **Step 1: Create pure-C++ `SignedMessage` header**

[firmware/esp32-recorder/src/crypto/SignedMessage.h](firmware/esp32-recorder/src/crypto/SignedMessage.h):

```cpp
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace locallexis::crypto {

constexpr const char* kSignDomainTagV2 = "locallexis-sig-v2";

// Builds the v2 signed message bytes:
//   "locallexis-sig-v2\n" + method + "\n" + target + "\n"
//   + timestamp + "\n" + nonce + "\n" + <32-byte digest>
//
// Pure C++ — host-testable. No Arduino types in the interface so this
// file can be compiled with plain g++ for the test/host/ harness.
std::vector<uint8_t> buildSignedMessageV2(
    const std::string& method,
    const std::string& target,
    const std::string& timestamp,
    const std::string& nonce,
    const uint8_t bodySha256[32]
);

}  // namespace locallexis::crypto
```

- [ ] **Step 2: Create `SignedMessage.cpp`**

[firmware/esp32-recorder/src/crypto/SignedMessage.cpp](firmware/esp32-recorder/src/crypto/SignedMessage.cpp):

```cpp
#include "crypto/SignedMessage.h"

#include <cstring>

namespace locallexis::crypto {

namespace {
void appendString(std::vector<uint8_t>& out, const std::string& s) {
    out.insert(out.end(), s.begin(), s.end());
}
}  // namespace

std::vector<uint8_t> buildSignedMessageV2(
    const std::string& method,
    const std::string& target,
    const std::string& timestamp,
    const std::string& nonce,
    const uint8_t bodySha256[32]
) {
    std::vector<uint8_t> out;
    const std::string tag = kSignDomainTagV2;
    out.reserve(tag.size() + method.size() + target.size()
                + timestamp.size() + nonce.size() + 32 + 5);
    appendString(out, tag);
    out.push_back('\n');
    appendString(out, method);
    out.push_back('\n');
    appendString(out, target);
    out.push_back('\n');
    appendString(out, timestamp);
    out.push_back('\n');
    appendString(out, nonce);
    out.push_back('\n');
    out.insert(out.end(), bodySha256, bodySha256 + 32);
    return out;
}

}  // namespace locallexis::crypto
```

- [ ] **Step 3: Add host-test Makefile**

[firmware/esp32-recorder/test/host/Makefile](firmware/esp32-recorder/test/host/Makefile):

```makefile
# Host (laptop) build of the firmware's pure-C++ modules. Each test binary
# links only the source files it actually needs so Arduino-only modules
# never enter the compile graph.
#
# Usage:
#   make            # build + run every test
#   make test_sign_v2 && ./test_sign_v2
#   make clean
#
# This sits beside platformio.ini's ESP32 builds — it does not feed into
# `pio run` and `pio run` does not feed into it.

CXX      ?= g++
CXXFLAGS ?= -std=c++17 -Wall -Wextra -Wpedantic -O2 -I../../src -I../../include

TESTS = test_provisioning_protocol test_hub_url test_sign_v2

.PHONY: all run clean
all: run

run: $(TESTS)
	@set -e; for t in $(TESTS); do echo "==> $$t"; ./$$t; done

test_provisioning_protocol: test_provisioning_protocol.cpp ../../src/provisioning/ProvisioningProtocol.cpp
	$(CXX) $(CXXFLAGS) -o $@ $^

test_hub_url: test_hub_url.cpp ../../src/net/HubUrl.cpp
	$(CXX) $(CXXFLAGS) -o $@ $^

test_sign_v2: test_sign_v2.cpp ../../src/crypto/SignedMessage.cpp
	$(CXX) $(CXXFLAGS) -o $@ $^

clean:
	rm -f $(TESTS)
```

- [ ] **Step 4: Verify the Makefile picks up existing tests (smoke)**

```bash
cd firmware/esp32-recorder/test/host && make test_provisioning_protocol test_hub_url && ./test_provisioning_protocol && ./test_hub_url && cd -
```

Expected: both binaries build and exit 0. If `ProvisioningProtocol.cpp` or `HubUrl.cpp` pulls Arduino headers, the build fails — but they don't (audited at plan time).

- [ ] **Step 5: Write `test_sign_v2.cpp` golden-vector test**

[firmware/esp32-recorder/test/host/test_sign_v2.cpp](firmware/esp32-recorder/test/host/test_sign_v2.cpp):

```cpp
#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

#include "crypto/SignedMessage.h"

using locallexis::crypto::buildSignedMessageV2;
using locallexis::crypto::kSignDomainTagV2;

namespace {

constexpr const char* kGoldenMsgHex =
    "6c6f63616c6c657869732d7369672d76320a504f53540a2f6a6f62732f75706c"
    "6f61643f66696c656e616d653d742e7761760a313730303030303030300a6162"
    "633132330a2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e730433"
    "62938b9824";

constexpr uint8_t kGoldenBodySha256[32] = {
    0x2c, 0xf2, 0x4d, 0xba, 0x5f, 0xb0, 0xa3, 0x0e,
    0x26, 0xe8, 0x3b, 0x2a, 0xc5, 0xb9, 0xe2, 0x9e,
    0x1b, 0x16, 0x1e, 0x5c, 0x1f, 0xa7, 0x42, 0x5e,
    0x73, 0x04, 0x33, 0x62, 0x93, 0x8b, 0x98, 0x24,
};

std::string toHex(const std::vector<uint8_t>& bytes) {
    static const char* hex = "0123456789abcdef";
    std::string out;
    out.reserve(bytes.size() * 2);
    for (uint8_t b : bytes) {
        out.push_back(hex[(b >> 4) & 0x0f]);
        out.push_back(hex[b & 0x0f]);
    }
    return out;
}

void test_domain_tag_is_locked() {
    assert(std::string(kSignDomainTagV2) == "locallexis-sig-v2");
}

void test_golden_vector_bytes_exact() {
    const auto msg = buildSignedMessageV2(
        "POST",
        "/jobs/upload?filename=t.wav",
        "1700000000",
        "abc123",
        kGoldenBodySha256
    );
    assert(msg.size() == 101);
    assert(toHex(msg) == kGoldenMsgHex);
}

void test_empty_body_digest_well_known_layout() {
    // sha256("") is the well-known e3b0c442… digest. We use a hand-rolled
    // 32-byte buffer here rather than computing it, because this test is
    // about message layout, not hashing.
    constexpr uint8_t kEmptyDigest[32] = {
        0xe3, 0xb0, 0xc4, 0x42, 0x98, 0xfc, 0x1c, 0x14,
        0x9a, 0xfb, 0xf4, 0xc8, 0x99, 0x6f, 0xb9, 0x24,
        0x27, 0xae, 0x41, 0xe4, 0x64, 0x9b, 0x93, 0x4c,
        0xa4, 0x95, 0x99, 0x1b, 0x78, 0x52, 0xb8, 0x55,
    };
    const auto msg = buildSignedMessageV2(
        "GET", "/sync/snapshot", "1700000000", "n", kEmptyDigest
    );
    const std::string prefix = "locallexis-sig-v2\nGET\n/sync/snapshot\n1700000000\nn\n";
    assert(msg.size() == prefix.size() + 32);
    assert(std::memcmp(msg.data(), prefix.data(), prefix.size()) == 0);
    assert(std::memcmp(msg.data() + prefix.size(), kEmptyDigest, 32) == 0);
}

}  // namespace

int main() {
    test_domain_tag_is_locked();
    test_golden_vector_bytes_exact();
    test_empty_body_digest_well_known_layout();
    std::cout << "test_sign_v2: OK" << std::endl;
    return 0;
}
```

- [ ] **Step 6: Build and run `test_sign_v2`**

```bash
cd firmware/esp32-recorder/test/host && make test_sign_v2 && ./test_sign_v2 && cd -
```

Expected output: `test_sign_v2: OK`. Any assertion fires `assert` → abort → non-zero exit, so the harness catches mismatches.

- [ ] **Step 7: Commit**

```bash
git add firmware/esp32-recorder/src/crypto/SignedMessage.h firmware/esp32-recorder/src/crypto/SignedMessage.cpp firmware/esp32-recorder/test/host/Makefile firmware/esp32-recorder/test/host/test_sign_v2.cpp
git commit -m "$(cat <<'EOF'
feat(firmware): pure-C++ v2 signed-message builder + host test harness

SignedMessage module produces the v2 byte layout (domain tag + method +
target + ts + nonce + 32-byte body digest) with no Arduino dependencies
so it host-tests via plain g++. Adds test/host/Makefile that picks up
the existing host tests plus the new golden-vector check.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Firmware — `DeviceCrypto` v2 signing on top of `SignedMessage`

**Files:**
- Modify: `firmware/esp32-recorder/src/crypto/DeviceCrypto.h`
- Modify: `firmware/esp32-recorder/src/crypto/DeviceCrypto.cpp`

- [ ] **Step 1: Update `DeviceCrypto.h` to expose digest-variant signer**

Replace [firmware/esp32-recorder/src/crypto/DeviceCrypto.h](firmware/esp32-recorder/src/crypto/DeviceCrypto.h):

```cpp
#pragma once

#include <Arduino.h>
#include <Ed25519.h>
#include <cstdint>

namespace locallexis::crypto {

struct DeviceKeys {
    uint8_t privateKey[32]{};
    uint8_t publicKey[32]{};
};

void deriveKeys(DeviceKeys& keys);
void generatePrivateKey(uint8_t privateKey[32]);

// Sign the v2 message for a body whose SHA-256 is already computed.
// Used by the streaming uploader so the full body never lives in RAM.
String signRequestB64WithBodyDigest(
    const DeviceKeys& keys,
    const String& method,
    const String& pathAndQuery,
    const String& timestamp,
    const String& nonce,
    const uint8_t bodySha256[32]
);

// Convenience for in-RAM bodies (small endpoints, tests). Hashes the
// body with mbedtls and delegates to the digest variant.
String signRequestB64(
    const DeviceKeys& keys,
    const String& method,
    const String& pathAndQuery,
    const String& timestamp,
    const String& nonce,
    const uint8_t* body,
    size_t bodyLen
);

String randomNonceHex();

}  // namespace locallexis::crypto
```

- [ ] **Step 2: Rewrite `DeviceCrypto.cpp` to delegate to `SignedMessage` + mbedtls hash**

Replace [firmware/esp32-recorder/src/crypto/DeviceCrypto.cpp](firmware/esp32-recorder/src/crypto/DeviceCrypto.cpp):

```cpp
#include "crypto/DeviceCrypto.h"

#include <string>
#include <vector>

#include <esp_random.h>
#include <mbedtls/sha256.h>

#include "crypto/Base64.h"
#include "crypto/SignedMessage.h"

namespace locallexis::crypto {

void generatePrivateKey(uint8_t privateKey[32]) {
    for (size_t i = 0; i < 32; i += 4) {
        const uint32_t word = esp_random();
        privateKey[i] = static_cast<uint8_t>(word & 0xff);
        privateKey[i + 1] = static_cast<uint8_t>((word >> 8) & 0xff);
        privateKey[i + 2] = static_cast<uint8_t>((word >> 16) & 0xff);
        privateKey[i + 3] = static_cast<uint8_t>((word >> 24) & 0xff);
    }
}

void deriveKeys(DeviceKeys& keys) {
    Ed25519::derivePublicKey(keys.publicKey, keys.privateKey);
}

String signRequestB64WithBodyDigest(
    const DeviceKeys& keys,
    const String& method,
    const String& pathAndQuery,
    const String& timestamp,
    const String& nonce,
    const uint8_t bodySha256[32]
) {
    const std::vector<uint8_t> message = buildSignedMessageV2(
        std::string(method.c_str()),
        std::string(pathAndQuery.c_str()),
        std::string(timestamp.c_str()),
        std::string(nonce.c_str()),
        bodySha256
    );

    uint8_t signature[64];
    Ed25519::sign(
        signature,
        keys.privateKey,
        keys.publicKey,
        message.data(),
        message.size()
    );
    return base64Encode(signature, sizeof(signature));
}

String signRequestB64(
    const DeviceKeys& keys,
    const String& method,
    const String& pathAndQuery,
    const String& timestamp,
    const String& nonce,
    const uint8_t* body,
    size_t bodyLen
) {
    uint8_t digest[32];
    mbedtls_sha256_ret(body, bodyLen, digest, 0);
    return signRequestB64WithBodyDigest(
        keys, method, pathAndQuery, timestamp, nonce, digest
    );
}

String randomNonceHex() {
    constexpr char hex[] = "0123456789abcdef";
    uint8_t raw[8];
    for (uint8_t& b : raw) {
        b = static_cast<uint8_t>(esp_random() & 0xff);
    }
    char out[17]{};
    for (size_t i = 0; i < sizeof(raw); ++i) {
        out[2 * i] = hex[(raw[i] >> 4) & 0x0f];
        out[2 * i + 1] = hex[raw[i] & 0x0f];
    }
    return String(out);
}

}  // namespace locallexis::crypto
```

- [ ] **Step 3: Build firmware to confirm Arduino path still compiles**

```bash
cd firmware/esp32-recorder && pio run -e waveshare-esp32-s3-epaper 2>&1 | tail -30 && cd -
```

Expected: `========= [SUCCESS] Took N seconds ===========` at the end. Any include error means `SignedMessage.h` or `mbedtls/sha256.h` is missing from the Arduino include path — usually fixed by including `<Arduino.h>` first.

- [ ] **Step 4: Commit**

```bash
git add firmware/esp32-recorder/src/crypto/DeviceCrypto.h firmware/esp32-recorder/src/crypto/DeviceCrypto.cpp
git commit -m "$(cat <<'EOF'
feat(firmware): DeviceCrypto signs v2 messages via SignedMessage builder

signRequestB64WithBodyDigest accepts a precomputed SHA-256 so the
streaming uploader can sign without ever holding the full body. The
existing signRequestB64 keeps its public shape but internally hashes
with mbedtls_sha256_ret then delegates — small endpoints (PATCH
relabel, in-RAM tests) are unaffected.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Firmware — `BodySource` + `VectorBodySource` + host tests

**Files:**
- Create: `firmware/esp32-recorder/src/net/BodySource.h`
- Create: `firmware/esp32-recorder/src/net/VectorBodySource.h`
- Create: `firmware/esp32-recorder/src/net/VectorBodySource.cpp`
- Create: `firmware/esp32-recorder/test/host/test_body_source.cpp`
- Modify: `firmware/esp32-recorder/test/host/Makefile`

- [ ] **Step 1: `BodySource.h` abstract interface**

[firmware/esp32-recorder/src/net/BodySource.h](firmware/esp32-recorder/src/net/BodySource.h):

```cpp
#pragma once

#include <cstddef>
#include <cstdint>

namespace locallexis::net {

// Abstract source of body bytes for the streaming uploader. Implementations
// supply two passes over the same byte range: one to compute the SHA-256
// for signing, one to write the body to the socket.
//
// Pure C++ — no Arduino types — so host tests can drive it directly.
class BodySource {
public:
    virtual ~BodySource() = default;

    // Total byte count. Used for the Content-Length header.
    virtual size_t size() const = 0;

    // Reset the read cursor to the start of the body. Returns true on
    // success; on failure the caller aborts the upload attempt.
    virtual bool rewind() = 0;

    // Read up to ``max`` bytes into ``buf``. Returns the number of bytes
    // actually read; 0 at end-of-stream. Returning a value larger than
    // ``max`` is a programming error.
    virtual size_t readChunk(uint8_t* buf, size_t max) = 0;
};

}  // namespace locallexis::net
```

- [ ] **Step 2: `VectorBodySource.h`**

[firmware/esp32-recorder/src/net/VectorBodySource.h](firmware/esp32-recorder/src/net/VectorBodySource.h):

```cpp
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "net/BodySource.h"

namespace locallexis::net {

// In-RAM BodySource backed by a std::vector. Holds a reference to the
// caller's buffer — caller must keep the buffer alive for the upload.
class VectorBodySource : public BodySource {
public:
    explicit VectorBodySource(const std::vector<uint8_t>& bytes);

    size_t size() const override { return bytes_.size(); }
    bool rewind() override;
    size_t readChunk(uint8_t* buf, size_t max) override;

private:
    const std::vector<uint8_t>& bytes_;
    size_t cursor_ = 0;
};

}  // namespace locallexis::net
```

- [ ] **Step 3: `VectorBodySource.cpp`**

[firmware/esp32-recorder/src/net/VectorBodySource.cpp](firmware/esp32-recorder/src/net/VectorBodySource.cpp):

```cpp
#include "net/VectorBodySource.h"

#include <algorithm>
#include <cstring>

namespace locallexis::net {

VectorBodySource::VectorBodySource(const std::vector<uint8_t>& bytes)
    : bytes_(bytes) {}

bool VectorBodySource::rewind() {
    cursor_ = 0;
    return true;
}

size_t VectorBodySource::readChunk(uint8_t* buf, size_t max) {
    if (cursor_ >= bytes_.size() || max == 0) {
        return 0;
    }
    const size_t remaining = bytes_.size() - cursor_;
    const size_t take = std::min(remaining, max);
    std::memcpy(buf, bytes_.data() + cursor_, take);
    cursor_ += take;
    return take;
}

}  // namespace locallexis::net
```

- [ ] **Step 4: Add `test_body_source` target to Makefile**

Modify [firmware/esp32-recorder/test/host/Makefile](firmware/esp32-recorder/test/host/Makefile). Update the `TESTS = ...` line:

```makefile
TESTS = test_provisioning_protocol test_hub_url test_sign_v2 test_body_source
```

Then append this build rule (the `SdFileBodySource.cpp` source is added in Task 6 and the rule is extended then; for this task the VectorBodySource-only rule is enough):

```makefile
test_body_source: test_body_source.cpp ../../src/net/VectorBodySource.cpp
	$(CXX) $(CXXFLAGS) -o $@ $^
```

- [ ] **Step 5: `test_body_source.cpp` — VectorBodySource scenarios**

[firmware/esp32-recorder/test/host/test_body_source.cpp](firmware/esp32-recorder/test/host/test_body_source.cpp):

```cpp
#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <numeric>
#include <vector>

#include "net/VectorBodySource.h"

using locallexis::net::VectorBodySource;

namespace {

std::vector<uint8_t> drain(VectorBodySource& src, size_t chunkSize) {
    std::vector<uint8_t> out;
    out.reserve(src.size());
    std::vector<uint8_t> buf(chunkSize);
    while (true) {
        const size_t n = src.readChunk(buf.data(), buf.size());
        if (n == 0) break;
        out.insert(out.end(), buf.begin(), buf.begin() + n);
    }
    return out;
}

void test_round_trip_full_buffer() {
    std::vector<uint8_t> bytes(257);
    std::iota(bytes.begin(), bytes.end(), 0);
    VectorBodySource src(bytes);
    assert(src.size() == bytes.size());
    auto got = drain(src, 4096);
    assert(got == bytes);
}

void test_round_trip_chunked_matches_whole() {
    std::vector<uint8_t> bytes(1000);
    for (size_t i = 0; i < bytes.size(); ++i) {
        bytes[i] = static_cast<uint8_t>(i & 0xff);
    }
    VectorBodySource a(bytes);
    auto whole = drain(a, bytes.size());
    assert(whole == bytes);

    VectorBodySource b(bytes);
    auto chunked = drain(b, 37);  // odd chunk size to stress boundary
    assert(chunked == bytes);
}

void test_rewind_replays_from_start() {
    std::vector<uint8_t> bytes = {1, 2, 3, 4, 5};
    VectorBodySource src(bytes);
    drain(src, 2);
    assert(src.rewind());
    auto second = drain(src, 2);
    assert(second == bytes);
}

void test_empty_body() {
    std::vector<uint8_t> bytes;
    VectorBodySource src(bytes);
    assert(src.size() == 0);
    uint8_t buf[16];
    assert(src.readChunk(buf, sizeof(buf)) == 0);
}

void test_zero_max_returns_zero_without_advancing() {
    std::vector<uint8_t> bytes = {9, 8, 7};
    VectorBodySource src(bytes);
    uint8_t buf[8];
    assert(src.readChunk(buf, 0) == 0);
    auto rest = drain(src, 8);
    assert(rest == bytes);
}

}  // namespace

int main() {
    test_round_trip_full_buffer();
    test_round_trip_chunked_matches_whole();
    test_rewind_replays_from_start();
    test_empty_body();
    test_zero_max_returns_zero_without_advancing();
    std::cout << "test_body_source: OK" << std::endl;
    return 0;
}
```

- [ ] **Step 6: Build + run host tests**

```bash
cd firmware/esp32-recorder/test/host && make test_body_source && ./test_body_source && cd -
```

Expected: `test_body_source: OK`.

- [ ] **Step 7: Confirm firmware still builds (Arduino path)**

```bash
cd firmware/esp32-recorder && pio run -e waveshare-esp32-s3-epaper 2>&1 | tail -10 && cd -
```

Expected: `[SUCCESS]`. `BodySource.h` is header-only and `VectorBodySource.cpp` is pure C++; picked up by `build_src_filter = +<*>` automatically.

- [ ] **Step 8: Commit**

```bash
git add firmware/esp32-recorder/src/net/BodySource.h firmware/esp32-recorder/src/net/VectorBodySource.h firmware/esp32-recorder/src/net/VectorBodySource.cpp firmware/esp32-recorder/test/host/test_body_source.cpp firmware/esp32-recorder/test/host/Makefile
git commit -m "$(cat <<'EOF'
feat(firmware): BodySource abstraction with in-RAM VectorBodySource impl

Two-pass interface (size/rewind/readChunk) gives the streaming uploader
exactly what it needs: one hash pass + one write pass over the same
bytes. Pure C++ for host-testability — five scenarios cover chunk
sizing, rewind, and the empty-body edge.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Firmware — `SdFileBodySource` over `FileLike` seam + host test

**Files:**
- Create: `firmware/esp32-recorder/src/storage/FileLike.h`
- Create: `firmware/esp32-recorder/src/storage/SdFile.h`
- Create: `firmware/esp32-recorder/src/storage/SdFile.cpp`
- Create: `firmware/esp32-recorder/src/storage/SdFileBodySource.h`
- Create: `firmware/esp32-recorder/src/storage/SdFileBodySource.cpp`
- Modify: `firmware/esp32-recorder/test/host/test_body_source.cpp`
- Modify: `firmware/esp32-recorder/test/host/Makefile`

- [ ] **Step 1: `FileLike.h` abstract seam**

[firmware/esp32-recorder/src/storage/FileLike.h](firmware/esp32-recorder/src/storage/FileLike.h):

```cpp
#pragma once

#include <cstddef>
#include <cstdint>

namespace locallexis::storage {

// Three-method seam that both the real Arduino SD_MMC File and a host-
// side fake implement. Lets SdFileBodySource stay pure C++ so the
// chunked-read logic can be exercised on a laptop without an SD card.
class FileLike {
public:
    virtual ~FileLike() = default;
    virtual size_t size() const = 0;
    virtual bool seekToStart() = 0;
    virtual size_t read(uint8_t* buf, size_t max) = 0;
};

}  // namespace locallexis::storage
```

- [ ] **Step 2: `SdFile.h` — Arduino impl (header only declares; .cpp wraps `SD_MMC::File`)**

[firmware/esp32-recorder/src/storage/SdFile.h](firmware/esp32-recorder/src/storage/SdFile.h):

```cpp
#pragma once

#include <Arduino.h>
#include <FS.h>

#include "storage/FileLike.h"

namespace locallexis::storage {

// FileLike adapter around an Arduino fs::File. Real impl only — never
// compiled into the host test binary.
class SdFile : public FileLike {
public:
    explicit SdFile(File file);
    ~SdFile() override;

    size_t size() const override;
    bool seekToStart() override;
    size_t read(uint8_t* buf, size_t max) override;

private:
    File file_;
    size_t size_ = 0;
};

}  // namespace locallexis::storage
```

- [ ] **Step 3: `SdFile.cpp`**

[firmware/esp32-recorder/src/storage/SdFile.cpp](firmware/esp32-recorder/src/storage/SdFile.cpp):

```cpp
#include "storage/SdFile.h"

namespace locallexis::storage {

SdFile::SdFile(File file) : file_(file) {
    size_ = file_ ? file_.size() : 0;
}

SdFile::~SdFile() {
    if (file_) {
        file_.close();
    }
}

size_t SdFile::size() const {
    return size_;
}

bool SdFile::seekToStart() {
    if (!file_) return false;
    return file_.seek(0);
}

size_t SdFile::read(uint8_t* buf, size_t max) {
    if (!file_ || max == 0) return 0;
    const int n = file_.read(buf, max);
    return n > 0 ? static_cast<size_t>(n) : 0;
}

}  // namespace locallexis::storage
```

- [ ] **Step 4: `SdFileBodySource.h` — pure C++ over FileLike**

[firmware/esp32-recorder/src/storage/SdFileBodySource.h](firmware/esp32-recorder/src/storage/SdFileBodySource.h):

```cpp
#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>

#include "net/BodySource.h"
#include "storage/FileLike.h"

namespace locallexis::storage {

// BodySource that pulls bytes from any FileLike. Owns the FileLike so
// the file handle is closed when the source is destroyed.
class SdFileBodySource : public locallexis::net::BodySource {
public:
    explicit SdFileBodySource(std::unique_ptr<FileLike> file);

    size_t size() const override;
    bool rewind() override;
    size_t readChunk(uint8_t* buf, size_t max) override;

private:
    std::unique_ptr<FileLike> file_;
};

}  // namespace locallexis::storage
```

- [ ] **Step 5: `SdFileBodySource.cpp`**

[firmware/esp32-recorder/src/storage/SdFileBodySource.cpp](firmware/esp32-recorder/src/storage/SdFileBodySource.cpp):

```cpp
#include "storage/SdFileBodySource.h"

namespace locallexis::storage {

SdFileBodySource::SdFileBodySource(std::unique_ptr<FileLike> file)
    : file_(std::move(file)) {}

size_t SdFileBodySource::size() const {
    return file_ ? file_->size() : 0;
}

bool SdFileBodySource::rewind() {
    return file_ && file_->seekToStart();
}

size_t SdFileBodySource::readChunk(uint8_t* buf, size_t max) {
    if (!file_ || max == 0) return 0;
    return file_->read(buf, max);
}

}  // namespace locallexis::storage
```

- [ ] **Step 6: Update Makefile build rule for `test_body_source` to include SdFileBodySource**

Modify [firmware/esp32-recorder/test/host/Makefile](firmware/esp32-recorder/test/host/Makefile) — replace the existing `test_body_source` rule with:

```makefile
test_body_source: test_body_source.cpp ../../src/net/VectorBodySource.cpp ../../src/storage/SdFileBodySource.cpp
	$(CXX) $(CXXFLAGS) -o $@ $^
```

- [ ] **Step 7: Extend `test_body_source.cpp` with `SdFileBodySource` + `FakeFileLike` tests**

Append these cases to [firmware/esp32-recorder/test/host/test_body_source.cpp](firmware/esp32-recorder/test/host/test_body_source.cpp), and add their calls to `main()`.

Add at the top of the file (alongside existing includes):

```cpp
#include <memory>
#include "storage/FileLike.h"
#include "storage/SdFileBodySource.h"
```

Add at the top of the anonymous namespace:

```cpp
class FakeFileLike : public locallexis::storage::FileLike {
public:
    explicit FakeFileLike(std::vector<uint8_t> bytes) : bytes_(std::move(bytes)) {}
    size_t size() const override { return bytes_.size(); }
    bool seekToStart() override { cursor_ = 0; return true; }
    size_t read(uint8_t* buf, size_t max) override {
        if (cursor_ >= bytes_.size() || max == 0) return 0;
        const size_t take = std::min(max, bytes_.size() - cursor_);
        std::memcpy(buf, bytes_.data() + cursor_, take);
        cursor_ += take;
        return take;
    }
private:
    std::vector<uint8_t> bytes_;
    size_t cursor_ = 0;
};
```

Add these test functions after `test_zero_max_returns_zero_without_advancing`:

```cpp
void test_sd_file_body_source_round_trip() {
    std::vector<uint8_t> bytes(513);
    for (size_t i = 0; i < bytes.size(); ++i) {
        bytes[i] = static_cast<uint8_t>((i * 7) & 0xff);
    }
    auto fake = std::make_unique<FakeFileLike>(bytes);
    locallexis::storage::SdFileBodySource src(std::move(fake));
    assert(src.size() == bytes.size());

    std::vector<uint8_t> got;
    std::vector<uint8_t> buf(64);
    while (true) {
        const size_t n = src.readChunk(buf.data(), buf.size());
        if (n == 0) break;
        got.insert(got.end(), buf.begin(), buf.begin() + n);
    }
    assert(got == bytes);
}

void test_sd_file_body_source_rewind() {
    std::vector<uint8_t> bytes = {10, 20, 30, 40};
    auto fake = std::make_unique<FakeFileLike>(bytes);
    locallexis::storage::SdFileBodySource src(std::move(fake));
    uint8_t buf[2];
    src.readChunk(buf, 2);
    assert(src.rewind());
    std::vector<uint8_t> got;
    uint8_t buf2[8];
    const size_t n = src.readChunk(buf2, sizeof(buf2));
    got.assign(buf2, buf2 + n);
    assert(got == bytes);
}
```

Update `main()` to call them (insert before `std::cout << ...`):

```cpp
    test_sd_file_body_source_round_trip();
    test_sd_file_body_source_rewind();
```

- [ ] **Step 8: Build + run extended host test**

```bash
cd firmware/esp32-recorder/test/host && make test_body_source && ./test_body_source && cd -
```

Expected: `test_body_source: OK`.

- [ ] **Step 9: Build firmware (Arduino path) — confirms `SdFile.cpp` compiles**

```bash
cd firmware/esp32-recorder && pio run -e waveshare-esp32-s3-epaper 2>&1 | tail -10 && cd -
```

Expected: `[SUCCESS]`. If `SdFile.cpp` errors on `File::seek` or `File::read`, the Arduino FS API may differ — check `<FS.h>` for the actual return types and adapt.

- [ ] **Step 10: Commit**

```bash
git add firmware/esp32-recorder/src/storage/FileLike.h firmware/esp32-recorder/src/storage/SdFile.h firmware/esp32-recorder/src/storage/SdFile.cpp firmware/esp32-recorder/src/storage/SdFileBodySource.h firmware/esp32-recorder/src/storage/SdFileBodySource.cpp firmware/esp32-recorder/test/host/test_body_source.cpp firmware/esp32-recorder/test/host/Makefile
git commit -m "$(cat <<'EOF'
feat(firmware): SdFileBodySource streams SD-card files through a FileLike seam

FileLike is a 3-method abstract that both SD_MMC's File and a host-side
FakeFileLike implement. SdFileBodySource owns one and exposes it as a
BodySource so meeting-length recordings stream off SD in 4 KB chunks
without ever loading the whole file. Host test exercises round-trip and
rewind through the fake; Arduino build verifies the SdFile wrapper.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Firmware — `SignedHttpClient::uploadWav(BodySource&)` streaming overload

**Files:**
- Modify: `firmware/esp32-recorder/src/net/SignedHttpClient.h`
- Modify: `firmware/esp32-recorder/src/net/SignedHttpClient.cpp`

- [ ] **Step 1: Add new overload to header**

Replace [firmware/esp32-recorder/src/net/SignedHttpClient.h](firmware/esp32-recorder/src/net/SignedHttpClient.h):

```cpp
#pragma once

#include <Arduino.h>
#include <vector>

#include "crypto/DeviceCrypto.h"
#include "net/BodySource.h"
#include "provisioning/ProvisioningProtocol.h"

namespace locallexis::net {

class SignedHttpClient {
public:
    // Streaming overload — preferred. Hashes the body in one pass, signs
    // the digest, then sends the body in a second pass without buffering.
    bool uploadWav(
        const locallexis::provisioning::ProvisioningConfig& cfg,
        const locallexis::crypto::DeviceKeys& keys,
        const String& filename,
        BodySource& source,
        String& response
    );

    // Convenience wrapper for in-RAM bodies (the demo silence-WAV path).
    // Wraps the vector in a VectorBodySource and calls the streaming
    // overload.
    bool uploadWav(
        const locallexis::provisioning::ProvisioningConfig& cfg,
        const locallexis::crypto::DeviceKeys& keys,
        const String& filename,
        const std::vector<uint8_t>& wavBytes,
        String& response
    );
};

std::vector<uint8_t> makeSilenceWav(uint32_t sampleRate, uint16_t seconds);

}  // namespace locallexis::net
```

- [ ] **Step 2: Rewrite `SignedHttpClient.cpp` for streaming**

Replace [firmware/esp32-recorder/src/net/SignedHttpClient.cpp](firmware/esp32-recorder/src/net/SignedHttpClient.cpp):

```cpp
#include "net/SignedHttpClient.h"

#include <algorithm>

#include <Client.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <mbedtls/sha256.h>
#include <mbedtls/x509_crt.h>
#include <time.h>

#include "crypto/Base64.h"
#include "net/HubUrl.h"
#include "net/VectorBodySource.h"

namespace locallexis::net {

namespace {
constexpr size_t kStreamChunkBytes = 4096;

String unixTimestamp() {
    return String(static_cast<unsigned long>(time(nullptr)));
}

bool verifySpkiPin(
    WiFiClientSecure& client,
    const locallexis::provisioning::ProvisioningConfig& cfg,
    String& response
) {
    const String expectedB64(cfg.tlsSpkiB64.c_str());
    if (expectedB64.isEmpty()) {
        response = "HTTPS hub is missing tls_spki_b64; refusing unpinned TLS upload";
        return false;
    }

    std::vector<uint8_t> expected;
    if (!locallexis::crypto::base64Decode(expectedB64, expected)
        || expected.size() != 32) {
        response = "tls_spki_b64 is not a 32-byte base64 SHA-256 digest";
        return false;
    }

    const mbedtls_x509_crt* cert = client.getPeerCertificate();
    if (cert == nullptr || cert->pk_raw.p == nullptr || cert->pk_raw.len == 0) {
        response = "TLS peer certificate is unavailable for SPKI pinning";
        return false;
    }

    uint8_t digest[32];
    if (mbedtls_sha256_ret(cert->pk_raw.p, cert->pk_raw.len, digest, 0) != 0) {
        response = "failed to hash TLS peer SPKI";
        return false;
    }
    if (!std::equal(expected.begin(), expected.end(), digest)) {
        response = "TLS SPKI pin mismatch";
        return false;
    }
    return true;
}

int parseStatusCode(const String& statusLine) {
    const int firstSpace = statusLine.indexOf(' ');
    if (firstSpace < 0) {
        return 0;
    }
    const int secondSpace = statusLine.indexOf(' ', firstSpace + 1);
    const String code = secondSpace > firstSpace
        ? statusLine.substring(firstSpace + 1, secondSpace)
        : statusLine.substring(firstSpace + 1);
    return code.toInt();
}

bool hashBody(BodySource& source, uint8_t digest[32], String& response) {
    if (!source.rewind()) {
        response = "failed to rewind body for hashing";
        return false;
    }
    mbedtls_sha256_context ctx;
    mbedtls_sha256_init(&ctx);
    if (mbedtls_sha256_starts_ret(&ctx, 0) != 0) {
        mbedtls_sha256_free(&ctx);
        response = "mbedtls_sha256_starts_ret failed";
        return false;
    }
    uint8_t buf[kStreamChunkBytes];
    while (true) {
        const size_t n = source.readChunk(buf, sizeof(buf));
        if (n == 0) break;
        if (mbedtls_sha256_update_ret(&ctx, buf, n) != 0) {
            mbedtls_sha256_free(&ctx);
            response = "mbedtls_sha256_update_ret failed";
            return false;
        }
    }
    if (mbedtls_sha256_finish_ret(&ctx, digest) != 0) {
        mbedtls_sha256_free(&ctx);
        response = "mbedtls_sha256_finish_ret failed";
        return false;
    }
    mbedtls_sha256_free(&ctx);
    return true;
}

bool writeRequestHeaders(
    Client& client,
    const HubUrl& hub,
    const String& pathAndQuery,
    const locallexis::provisioning::ProvisioningConfig& cfg,
    const String& timestamp,
    const String& nonce,
    const String& signature,
    size_t contentLength
) {
    client.print("POST ");
    client.print(pathAndQuery);
    client.print(" HTTP/1.1\r\nHost: ");
    client.print(hub.host.c_str());
    client.print(":");
    client.print(hub.port);
    client.print("\r\nConnection: close\r\nAccept: application/json\r\nContent-Type: audio/wav\r\nContent-Length: ");
    client.print(static_cast<unsigned long>(contentLength));
    client.print("\r\nX-Device-Id: ");
    client.print(cfg.deviceId.c_str());
    client.print("\r\nX-Timestamp: ");
    client.print(timestamp);
    client.print("\r\nX-Nonce: ");
    client.print(nonce);
    client.print("\r\nX-Signature-B64: ");
    client.print(signature);
    client.print("\r\n\r\n");
    return true;
}

bool streamBodyToSocket(
    Client& client,
    BodySource& source,
    size_t expectedSize,
    String& response
) {
    if (!source.rewind()) {
        response = "failed to rewind body for upload";
        return false;
    }
    size_t sent = 0;
    uint8_t buf[kStreamChunkBytes];
    while (true) {
        const size_t n = source.readChunk(buf, sizeof(buf));
        if (n == 0) break;
        const size_t wrote = client.write(buf, n);
        if (wrote != n) {
            response = "short socket write while streaming body";
            return false;
        }
        sent += n;
    }
    if (sent != expectedSize) {
        response = "body size changed between hash and write passes";
        return false;
    }
    return true;
}

bool readUploadResponse(Client& client, String& response) {
    String statusLine = client.readStringUntil('\n');
    statusLine.trim();
    const int status = parseStatusCode(statusLine);
    response = statusLine;

    const unsigned long deadline = millis() + 10000;
    while (millis() < deadline) {
        while (client.available()) {
            response += static_cast<char>(client.read());
        }
        if (!client.connected()) {
            break;
        }
        delay(10);
    }
    return status == 202;
}

void appendLe16(std::vector<uint8_t>& out, uint16_t value) {
    out.push_back(static_cast<uint8_t>(value & 0xff));
    out.push_back(static_cast<uint8_t>((value >> 8) & 0xff));
}

void appendLe32(std::vector<uint8_t>& out, uint32_t value) {
    out.push_back(static_cast<uint8_t>(value & 0xff));
    out.push_back(static_cast<uint8_t>((value >> 8) & 0xff));
    out.push_back(static_cast<uint8_t>((value >> 16) & 0xff));
    out.push_back(static_cast<uint8_t>((value >> 24) & 0xff));
}

void appendAscii(std::vector<uint8_t>& out, const char* text) {
    while (*text) {
        out.push_back(static_cast<uint8_t>(*text++));
    }
}
}  // namespace

bool SignedHttpClient::uploadWav(
    const locallexis::provisioning::ProvisioningConfig& cfg,
    const locallexis::crypto::DeviceKeys& keys,
    const String& filename,
    BodySource& source,
    String& response
) {
    HubUrl hub;
    std::string urlError;
    if (!parseHubUrl(cfg.hubUrl, hub, urlError)) {
        response = urlError.c_str();
        return false;
    }

    const String pathAndQuery = hubPath(
        hub,
        std::string("/jobs/upload?filename=") + filename.c_str()
    ).c_str();

    uint8_t bodyDigest[32];
    if (!hashBody(source, bodyDigest, response)) {
        return false;
    }

    const String ts = unixTimestamp();
    const String nonce = locallexis::crypto::randomNonceHex();
    const String sig = locallexis::crypto::signRequestB64WithBodyDigest(
        keys, "POST", pathAndQuery, ts, nonce, bodyDigest
    );

    auto run = [&](Client& client) -> bool {
        writeRequestHeaders(client, hub, pathAndQuery, cfg, ts, nonce, sig, source.size());
        if (!streamBodyToSocket(client, source, source.size(), response)) {
            return false;
        }
        return readUploadResponse(client, response);
    };

    if (hub.https) {
        WiFiClientSecure secureClient;
        secureClient.setInsecure();
        if (!secureClient.connect(hub.host.c_str(), hub.port)) {
            response = "failed to connect to HTTPS hub";
            return false;
        }
        if (!verifySpkiPin(secureClient, cfg, response)) {
            secureClient.stop();
            return false;
        }
        const bool ok = run(secureClient);
        secureClient.stop();
        return ok;
    }

    WiFiClient plainClient;
    if (!plainClient.connect(hub.host.c_str(), hub.port)) {
        response = "failed to connect to HTTP hub";
        return false;
    }
    const bool ok = run(plainClient);
    plainClient.stop();
    return ok;
}

bool SignedHttpClient::uploadWav(
    const locallexis::provisioning::ProvisioningConfig& cfg,
    const locallexis::crypto::DeviceKeys& keys,
    const String& filename,
    const std::vector<uint8_t>& wavBytes,
    String& response
) {
    VectorBodySource source(wavBytes);
    return uploadWav(cfg, keys, filename, source, response);
}

std::vector<uint8_t> makeSilenceWav(uint32_t sampleRate, uint16_t seconds) {
    const uint16_t channels = 1;
    const uint16_t bitsPerSample = 16;
    const uint32_t dataBytes = sampleRate * seconds * channels * (bitsPerSample / 8);
    std::vector<uint8_t> out;
    out.reserve(44 + dataBytes);

    appendAscii(out, "RIFF");
    appendLe32(out, 36 + dataBytes);
    appendAscii(out, "WAVE");
    appendAscii(out, "fmt ");
    appendLe32(out, 16);
    appendLe16(out, 1);
    appendLe16(out, channels);
    appendLe32(out, sampleRate);
    appendLe32(out, sampleRate * channels * (bitsPerSample / 8));
    appendLe16(out, channels * (bitsPerSample / 8));
    appendLe16(out, bitsPerSample);
    appendAscii(out, "data");
    appendLe32(out, dataBytes);
    out.insert(out.end(), dataBytes, 0);
    return out;
}

}  // namespace locallexis::net
```

- [ ] **Step 3: Build firmware**

```bash
cd firmware/esp32-recorder && pio run -e waveshare-esp32-s3-epaper 2>&1 | tail -10 && cd -
```

Expected: `[SUCCESS]`. The existing demo path in `main.cpp` keeps calling the vector overload — no caller changes yet.

- [ ] **Step 4: Commit**

```bash
git add firmware/esp32-recorder/src/net/SignedHttpClient.h firmware/esp32-recorder/src/net/SignedHttpClient.cpp
git commit -m "$(cat <<'EOF'
feat(firmware): SignedHttpClient streams uploads via BodySource

New uploadWav(BodySource&) overload runs two passes — mbedtls SHA-256
streaming hash, then socket write — with a single 4 KB scratch buffer
between them. Vector overload becomes a thin wrapper around a
VectorBodySource so the existing demo path is unaffected. No body of
any size ever lives fully in RAM.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Firmware — `SdQueue` peek-by-path + reader; `main.cpp` drain switch

**Files:**
- Modify: `firmware/esp32-recorder/src/storage/SdQueue.h`
- Modify: `firmware/esp32-recorder/src/storage/SdQueue.cpp`
- Modify: `firmware/esp32-recorder/src/main.cpp`

- [ ] **Step 1: Update `SdQueue.h` — replace `peekOldest` with `peekOldestPath` + `openReader`**

Replace [firmware/esp32-recorder/src/storage/SdQueue.h](firmware/esp32-recorder/src/storage/SdQueue.h):

```cpp
#pragma once

#include <Arduino.h>
#include <Preferences.h>
#include <memory>
#include <vector>

#include "storage/SdFileBodySource.h"

namespace locallexis::storage {

struct QueueStats {
    uint32_t pending = 0;
    uint64_t totalBytes = 0;
    uint64_t usedBytes = 0;
};

class SdQueue {
public:
    bool begin(int clkPin, int cmdPin, int d0Pin,
               const char* queueDir = "/queue");
    bool ready() const { return ready_; }
    bool enqueue(const std::vector<uint8_t>& wavBytes, String* outPath = nullptr);

    // Returns the path of the oldest queued .wav without reading its bytes.
    bool peekOldestPath(String& outPath);

    // Opens a streaming reader for ``path`` (must be inside the queue dir).
    // Returns nullptr if the file cannot be opened.
    std::unique_ptr<SdFileBodySource> openReader(const String& path);

    bool removeFile(const String& path);
    QueueStats stats();

private:
    bool ready_ = false;
    String queueDir_;
    Preferences prefs_;
    uint64_t nextN_ = 1;

    bool sweepPartials();
    String nextFilenameStem();
};

}  // namespace locallexis::storage
```

- [ ] **Step 2: Update `SdQueue.cpp`**

In [firmware/esp32-recorder/src/storage/SdQueue.cpp](firmware/esp32-recorder/src/storage/SdQueue.cpp), replace the `peekOldest` function (lines 121-157) with the two new functions, and add the `SdFile` include at top:

Add to includes:

```cpp
#include "storage/SdFile.h"
```

Replace the entire `peekOldest` function block with:

```cpp
bool SdQueue::peekOldestPath(String& outPath) {
    if (!ready_) return false;
    File root = SD_MMC.open(queueDir_);
    if (!root || !root.isDirectory()) {
        if (root) root.close();
        return false;
    }

    String oldest;
    File entry = root.openNextFile();
    while (entry) {
        const String name = entry.name();
        if (!entry.isDirectory() && name.endsWith(".wav")) {
            if (oldest.isEmpty() || name < oldest) {
                oldest = name;
            }
        }
        entry.close();
        entry = root.openNextFile();
    }
    root.close();
    if (oldest.isEmpty()) return false;

    outPath = fullPathOf(queueDir_, oldest);
    return true;
}

std::unique_ptr<SdFileBodySource> SdQueue::openReader(const String& path) {
    if (!ready_) return nullptr;
    File f = SD_MMC.open(path, FILE_READ);
    if (!f) return nullptr;
    auto file = std::unique_ptr<FileLike>(new SdFile(f));
    return std::unique_ptr<SdFileBodySource>(new SdFileBodySource(std::move(file)));
}
```

- [ ] **Step 3: Update `main.cpp` drain loop**

In [firmware/esp32-recorder/src/main.cpp:151-186](firmware/esp32-recorder/src/main.cpp:151), replace `drainQueueStep` with:

```cpp
void drainQueueStep() {
    if (!g_sdQueue.ready()
        || !g_identity.provisioned
        || WiFi.status() != WL_CONNECTED) {
        return;
    }

    String path;
    if (!g_sdQueue.peekOldestPath(path)) {
        return;
    }

    auto reader = g_sdQueue.openReader(path);
    if (!reader) {
        Serial.printf("Drain: could not open %s\n", path.c_str());
        delay(2000);
        return;
    }

    const int slash = path.lastIndexOf('/');
    const String filename = slash >= 0 ? path.substring(slash + 1) : path;

    Serial.printf("Draining %s (%u bytes)\n",
                  filename.c_str(),
                  static_cast<unsigned>(reader->size()));
    String response;
    locallexis::net::SignedHttpClient client;
    const bool ok = client.uploadWav(
        g_identity.provisioning,
        g_identity.keys,
        filename,
        *reader,
        response
    );
    Serial.printf("Drain result: %s\n%s\n", ok ? "ok" : "failed", response.c_str());

    if (ok) {
        g_sdQueue.removeFile(path);
    } else {
        delay(2000);
    }
}
```

- [ ] **Step 4: Build firmware**

```bash
cd firmware/esp32-recorder && pio run -e waveshare-esp32-s3-epaper 2>&1 | tail -15 && cd -
```

Expected: `[SUCCESS]`. If `<memory>` is not pulled in transitively, add `#include <memory>` to `SdQueue.cpp`.

- [ ] **Step 5: Commit**

```bash
git add firmware/esp32-recorder/src/storage/SdQueue.h firmware/esp32-recorder/src/storage/SdQueue.cpp firmware/esp32-recorder/src/main.cpp
git commit -m "$(cat <<'EOF'
feat(firmware): SdQueue exposes streaming reader; drain stops loading whole WAVs

peekOldestPath walks the queue dir without opening anything; openReader
hands back an SdFileBodySource that the uploader can drain in 4 KB
chunks. Removes peekOldest entirely — main.cpp's drain loop now goes
peek → open → stream → remove instead of peek-into-RAM → upload.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Firmware — add `LOCALLEXIS_PROTO_VERSION 2` build flag

**Files:**
- Modify: `firmware/esp32-recorder/platformio.ini`

- [ ] **Step 1: Add the define to the main env**

In [firmware/esp32-recorder/platformio.ini](firmware/esp32-recorder/platformio.ini), under `[env:waveshare-esp32-s3-epaper]` `build_flags`, append `-DLOCALLEXIS_PROTO_VERSION=2`:

```ini
build_flags =
  -std=gnu++17
  -DBOARD_HAS_PSRAM
  -DARDUINO_USB_CDC_ON_BOOT=1
  -DARDUINO_USB_MODE=1
  -DCORE_DEBUG_LEVEL=3
  -DLOCALLEXIS_PROTO_VERSION=2
```

The `wokwi-sim` env extends this so it inherits the define automatically.

- [ ] **Step 2: Build to confirm flag accepted**

```bash
cd firmware/esp32-recorder && pio run -e waveshare-esp32-s3-epaper 2>&1 | tail -5 && cd -
```

Expected: `[SUCCESS]`. The define is unused at compile time today; it exists for traceability (boot log can read it via `Serial.printf("Protocol v%d", LOCALLEXIS_PROTO_VERSION)` if needed later).

- [ ] **Step 3: Commit**

```bash
git add firmware/esp32-recorder/platformio.ini
git commit -m "$(cat <<'EOF'
chore(firmware): pin LOCALLEXIS_PROTO_VERSION=2 for traceability

The firmware has no version file, so the protocol version lives as a
build flag instead. Inherited by the wokwi-sim env via extends.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Android — `buildRequestMessage` v2 + test updates

**Files:**
- Modify: `android/app/src/main/kotlin/app/locallexis/data/crypto/CryptoBox.kt`
- Modify: `android/app/src/test/kotlin/app/locallexis/data/crypto/CryptoBoxTest.kt`
- Modify: `android/app/src/test/kotlin/app/locallexis/data/pairing/SignedRequestInterceptorTest.kt`

- [ ] **Step 1: Update `CryptoBox.kt` — kdoc + `buildRequestMessage` v2**

In [android/app/src/main/kotlin/app/locallexis/data/crypto/CryptoBox.kt](android/app/src/main/kotlin/app/locallexis/data/crypto/CryptoBox.kt), update the `signRequest` kdoc (lines 17-22) to describe v2:

```kotlin
    /**
     * Detached Ed25519 signature over the v2 replay-protected hub
     * request bytes:
     *
     *   "locallexis-sig-v2" + "\n" + [method] + "\n" +
     *   [path]["?" + [query]] + "\n" + [timestamp] + "\n" +
     *   [nonce] + "\n" + sha256([body])
     *
     * The body digest (32 raw bytes) is signed instead of the body so
     * the message stays ~90 bytes regardless of upload size.
     */
```

Replace the `buildRequestMessage` function (lines 149-163) and the `NEWLINE` constant with:

```kotlin
internal fun buildRequestMessage(
    method: String,
    path: String,
    query: String,
    timestamp: String,
    nonce: String,
    body: ByteArray,
): ByteArray {
    val target = if (query.isBlank()) path else "$path?$query"
    val bodyDigest = java.security.MessageDigest.getInstance("SHA-256").digest(body)
    val parts = listOf(
        SIGN_DOMAIN_TAG_V2.toByteArray(),
        method.toByteArray(),
        target.toByteArray(),
        timestamp.toByteArray(),
        nonce.toByteArray(),
        bodyDigest,
    )
    val totalSize = parts.sumOf { it.size } + (parts.size - 1)
    val out = ByteArray(totalSize)
    var offset = 0
    for ((index, part) in parts.withIndex()) {
        part.copyInto(out, offset)
        offset += part.size
        if (index < parts.lastIndex) {
            out[offset] = 0x0A
            offset += 1
        }
    }
    return out
}

private const val SIGN_DOMAIN_TAG_V2 = "locallexis-sig-v2"
```

- [ ] **Step 2: Update `CryptoBoxTest.kt` — v2 expectations + golden vector**

In [android/app/src/test/kotlin/app/locallexis/data/crypto/CryptoBoxTest.kt](android/app/src/test/kotlin/app/locallexis/data/crypto/CryptoBoxTest.kt), replace the `signRequestVerifiesAgainstDevicePublicKey` and `signRequestEmptyBody` tests (lines 50-91) with v2 versions, and add a golden-vector test:

```kotlin
    @Test
    fun signRequestVerifiesAgainstDevicePublicKey() {
        val pubkey = crypto.devicePublicKey()
        val body = """{"foo":"bar"}""".toByteArray()
        val sig = crypto.signRequest(
            method = "POST",
            path = "/v1/relabel",
            query = "",
            timestamp = "1716200000",
            nonce = "abc123",
            body = body,
        )

        assertEquals(Sign.BYTES, sig.size)
        val nl = byteArrayOf(0x0A)
        val bodyDigest = java.security.MessageDigest.getInstance("SHA-256").digest(body)
        val message = "locallexis-sig-v2".toByteArray() + nl +
            "POST".toByteArray() + nl +
            "/v1/relabel".toByteArray() + nl +
            "1716200000".toByteArray() + nl +
            "abc123".toByteArray() + nl +
            bodyDigest
        val ok = sodium.cryptoSignVerifyDetached(sig, message, message.size, pubkey)
        assertTrue("v2 signature verification", ok)
    }

    @Test
    fun signRequestEmptyBody() {
        val pubkey = crypto.devicePublicKey()
        val sig = crypto.signRequest(
            method = "GET",
            path = "/sync/snapshot",
            query = "limit=2",
            timestamp = "1716200001",
            nonce = "def456",
            body = ByteArray(0),
        )

        val nl = byteArrayOf(0x0A)
        val emptyDigest = java.security.MessageDigest.getInstance("SHA-256").digest(ByteArray(0))
        val message = "locallexis-sig-v2".toByteArray() + nl +
            "GET".toByteArray() + nl +
            "/sync/snapshot?limit=2".toByteArray() + nl +
            "1716200001".toByteArray() + nl +
            "def456".toByteArray() + nl +
            emptyDigest
        val ok = sodium.cryptoSignVerifyDetached(sig, message, message.size, pubkey)
        assertTrue(ok)
    }

    @Test
    fun signRequestMatchesCrossLanguageGoldenVector() {
        // Same vector as the hub's test_auth_v2.py and the firmware's
        // test_sign_v2.cpp. Three implementations must agree byte-for-byte.
        val goldenSeed = ByteArray(32) { it.toByte() }
        val sodium = LazySodiumJava(SodiumJava())
        val pk = ByteArray(Sign.PUBLICKEYBYTES)
        val sk = ByteArray(Sign.SECRETKEYBYTES)
        assertTrue(sodium.cryptoSignSeedKeypair(pk, sk, goldenSeed))

        val storage = InMemorySecretStorage().apply { putSecretSeed(goldenSeed) }
        val box = LazysodiumCryptoBox(storage, sodium)

        val sig = box.signRequest(
            method = "POST",
            path = "/jobs/upload",
            query = "filename=t.wav",
            timestamp = "1700000000",
            nonce = "abc123",
            body = "hello".toByteArray(),
        )
        val sigB64 = java.util.Base64.getEncoder().encodeToString(sig)
        assertEquals(
            "/OsfsMPLhgXoE+9izzKmxXq2JNcuGhUu6FbF23WnPYfqJQieQrYMTc8AbDa+g5j/" +
                "WonMiJpvQpspFU8DbgpZAw==",
            sigB64,
        )
    }
```

- [ ] **Step 3: Update `SignedRequestInterceptorTest.kt` — v2 expectations**

In [android/app/src/test/kotlin/app/locallexis/data/pairing/SignedRequestInterceptorTest.kt](android/app/src/test/kotlin/app/locallexis/data/pairing/SignedRequestInterceptorTest.kt), update three tests to expect v2 message bytes.

Replace the `addsDeviceIdAndSignatureHeaders` test (lines 45-70):

```kotlin
    @Test
    fun addsDeviceIdAndSignatureHeaders() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))

        val req = Request.Builder()
            .url(server.url("/sync/snapshot"))
            .get()
            .build()

        http.newCall(req).execute().close()

        val recorded = server.takeRequest()
        assertEquals("dev_abc", recorded.getHeader("X-Device-Id"))
        val sigB64 = recorded.getHeader("X-Signature-B64")
        assertNotNull("signature header present", sigB64)

        val timestamp = recorded.getHeader("X-Timestamp")
        val nonce = recorded.getHeader("X-Nonce")
        assertNotNull("timestamp header present", timestamp)
        assertNotNull("nonce header present", nonce)
        val emptyDigest = java.security.MessageDigest.getInstance("SHA-256").digest(ByteArray(0))
        val message = "locallexis-sig-v2".toByteArray() + byteArrayOf(0x0A) +
            "GET".toByteArray() + byteArrayOf(0x0A) +
            "/sync/snapshot".toByteArray() + byteArrayOf(0x0A) +
            "$timestamp".toByteArray() + byteArrayOf(0x0A) +
            "$nonce".toByteArray() + byteArrayOf(0x0A) +
            emptyDigest
        val sig = Base64.getDecoder().decode(sigB64)
        val ok = sodium.cryptoSignVerifyDetached(sig, message, message.size, crypto.devicePublicKey())
        assertTrue("v2 signature verifies", ok)
    }
```

Replace the `signsQueryTimestampAndNonceForReplayProtectedHubAuth` test (lines 72-100):

```kotlin
    @Test
    fun signsQueryTimestampAndNonceForReplayProtectedHubAuth() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))

        val req = Request.Builder()
            .url(server.url("/sync/snapshot?limit=2&offset=4"))
            .get()
            .build()

        http.newCall(req).execute().close()

        val recorded = server.takeRequest()
        val timestamp = recorded.getHeader("X-Timestamp")
        val nonce = recorded.getHeader("X-Nonce")
        val sigB64 = recorded.getHeader("X-Signature-B64")
        assertNotNull("timestamp header present", timestamp)
        assertNotNull("nonce header present", nonce)
        assertNotNull("signature header present", sigB64)
        assertTrue("nonce is 128-bit hex", nonce!!.matches(Regex("[0-9a-f]{32}")))

        val emptyDigest = java.security.MessageDigest.getInstance("SHA-256").digest(ByteArray(0))
        val message = "locallexis-sig-v2".toByteArray() + byteArrayOf(0x0A) +
            "GET".toByteArray() + byteArrayOf(0x0A) +
            "/sync/snapshot?limit=2&offset=4".toByteArray() + byteArrayOf(0x0A) +
            "$timestamp".toByteArray() + byteArrayOf(0x0A) +
            "$nonce".toByteArray() + byteArrayOf(0x0A) +
            emptyDigest
        val sig = Base64.getDecoder().decode(sigB64)
        val ok = sodium.cryptoSignVerifyDetached(sig, message, message.size, crypto.devicePublicKey())
        assertTrue("v2 signature verifies against replay-protected hub bytes", ok)
    }
```

Replace the `signsPatchBody` test (lines 102-124):

```kotlin
    @Test
    fun signsPatchBody() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))

        val body = """{"key":"speakers.SPEAKER_00","value":"Alice"}""".toByteArray()
        val req = Request.Builder()
            .url(server.url("/transcripts/abc/relabel"))
            .patch(body.toRequestBody())
            .build()

        http.newCall(req).execute().close()

        val recorded = server.takeRequest()
        val sigB64 = recorded.getHeader("X-Signature-B64")!!
        val timestamp = recorded.getHeader("X-Timestamp")
        val nonce = recorded.getHeader("X-Nonce")
        assertNotNull("timestamp header present", timestamp)
        assertNotNull("nonce header present", nonce)
        val bodyDigest = java.security.MessageDigest.getInstance("SHA-256").digest(body)
        val message = "locallexis-sig-v2".toByteArray() + byteArrayOf(0x0A) +
            "PATCH".toByteArray() + byteArrayOf(0x0A) +
            "/transcripts/abc/relabel".toByteArray() + byteArrayOf(0x0A) +
            "$timestamp".toByteArray() + byteArrayOf(0x0A) +
            "$nonce".toByteArray() + byteArrayOf(0x0A) +
            bodyDigest
        val sig = Base64.getDecoder().decode(sigB64)
        val ok = sodium.cryptoSignVerifyDetached(sig, message, message.size, crypto.devicePublicKey())
        assertTrue(ok)
    }
```

The remaining tests (`rejectsOversizedSignedBody`, `signsLargeBodyWhenTaggedForUpload`, `unregisteredDeviceSkipsSigning`) test interceptor behavior (size cap, header presence) — not byte format — so they need no changes.

- [ ] **Step 4: Run Android unit tests**

```bash
cd android && ./gradlew :app:testDebugUnitTest --tests "app.locallexis.data.crypto.*" --tests "app.locallexis.data.pairing.*" --tests "app.locallexis.data.sync.*" 2>&1 | tail -40 && cd -
```

Expected: BUILD SUCCESSFUL. All updated tests pass and the existing `SyncClientTest` continues to pass (it only checks `X-Device-Id` + `X-Signature-B64` header *presence*, not byte content, per [SyncClientTest.kt:86-87](android/app/src/test/kotlin/app/locallexis/data/sync/SyncClientTest.kt:86)).

- [ ] **Step 5: Commit**

```bash
git add android/app/src/main/kotlin/app/locallexis/data/crypto/CryptoBox.kt android/app/src/test/kotlin/app/locallexis/data/crypto/CryptoBoxTest.kt android/app/src/test/kotlin/app/locallexis/data/pairing/SignedRequestInterceptorTest.kt
git commit -m "$(cat <<'EOF'
feat(android): CryptoBox.buildRequestMessage emits v2 signed bytes

Prepends the locallexis-sig-v2 domain tag and replaces the raw body
with its SHA-256 digest. CryptoBoxTest gains a cross-language golden-
vector test that pins the same base64 signature the hub and firmware
tests assert. The Android upload path keeps buffering the body (the
interceptor needs a known-length, non-one-shot body to compute the
digest) — streaming Android is deferred per the spec.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Version bumps + README

**Files:**
- Modify: `pyproject.toml`
- Modify: `android/app/build.gradle.kts`
- Modify: `ui/package.json`
- Modify: `ui/src-tauri/Cargo.toml`
- Modify: `ui/src-tauri/tauri.conf.json`
- Modify: `firmware/esp32-recorder/README.md`

- [ ] **Step 1: Bump `pyproject.toml`**

In [pyproject.toml](pyproject.toml) change:

```toml
version = "0.9.4"
```

to:

```toml
version = "0.9.5"
```

- [ ] **Step 2: Bump `android/app/build.gradle.kts`**

In [android/app/build.gradle.kts](android/app/build.gradle.kts), change:

```kotlin
        versionCode = 7
        versionName = "0.9.4"
```

to:

```kotlin
        versionCode = 8
        versionName = "0.9.5"
```

- [ ] **Step 3: Bump `ui/package.json`**

In [ui/package.json](ui/package.json), change:

```json
  "version": "0.9.4",
```

to:

```json
  "version": "0.9.5",
```

- [ ] **Step 4: Bump `ui/src-tauri/Cargo.toml`**

In [ui/src-tauri/Cargo.toml](ui/src-tauri/Cargo.toml), change:

```toml
version = "0.9.3"
```

to:

```toml
version = "0.9.5"
```

- [ ] **Step 5: Bump `ui/src-tauri/tauri.conf.json`**

In [ui/src-tauri/tauri.conf.json](ui/src-tauri/tauri.conf.json), change:

```json
  "version": "0.9.3",
```

to:

```json
  "version": "0.9.5",
```

- [ ] **Step 6: Update firmware README**

Read [firmware/esp32-recorder/README.md](firmware/esp32-recorder/README.md) — locate the "Current Limits" section (or the closest equivalent describing the upload protocol / RAM ceiling) and add a one-line bullet:

```markdown
- Protocol v2 (sha256(body) signing + streaming upload, gated by
  `LOCALLEXIS_PROTO_VERSION=2`): one-hour 16 kHz mono 16-bit recordings
  upload through a 4 KB streaming buffer with no full-body allocation.
```

If "Current Limits" does not exist, add a "Protocol" section at a sensible point (after the build/flash instructions). Reading the file is mandatory — do not blindly append.

- [ ] **Step 7: Sanity-check versions are aligned**

```bash
echo "--- pyproject ---" && grep '^version' pyproject.toml
echo "--- android ---" && grep -E "versionName|versionCode" android/app/build.gradle.kts
echo "--- ui/package.json ---" && grep '"version"' ui/package.json | head -1
echo "--- ui/src-tauri/Cargo.toml ---" && grep '^version' ui/src-tauri/Cargo.toml
echo "--- ui/src-tauri/tauri.conf.json ---" && grep '"version"' ui/src-tauri/tauri.conf.json | head -1
```

Expected: every line shows `0.9.5` (or `versionName = "0.9.5"` / `versionCode = 8`).

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml android/app/build.gradle.kts ui/package.json ui/src-tauri/Cargo.toml ui/src-tauri/tauri.conf.json firmware/esp32-recorder/README.md
git commit -m "$(cat <<'EOF'
chore: bump to 0.9.5 for protocol-v2 hard-cut deploy

Hub, Android, UI, and Tauri shell aligned at 0.9.5 (Tauri also lifted
from 0.9.3 to catch up). Firmware README notes the v2 streaming-upload
guarantee.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Full-suite verification

**Files:** none modified.

- [ ] **Step 1: Run the fast hub suite**

```bash
.venv/bin/pytest -m "not integration" 2>&1 | tail -20
```

Expected: all PASS. If the suite reports unrelated failures, isolate by running only the touched files:

```bash
.venv/bin/pytest tests/api/test_auth.py tests/api/test_auth_v2.py tests/api/test_routes_ingest.py tests/api/test_routes_ingest_v2.py tests/api/test_routes_sync.py tests/api/test_routes_transcripts.py -v
```

- [ ] **Step 2: Run host firmware tests**

```bash
cd firmware/esp32-recorder/test/host && make clean && make && cd -
```

Expected: `test_provisioning_protocol: OK`, `test_hub_url`-equivalent OK (binary just exits 0), `test_sign_v2: OK`, `test_body_source: OK`.

- [ ] **Step 3: Build firmware for the real board**

```bash
cd firmware/esp32-recorder && pio run -e waveshare-esp32-s3-epaper 2>&1 | tail -10 && cd -
```

Expected: `[SUCCESS]`.

- [ ] **Step 4: Run Android unit tests**

```bash
cd android && ./gradlew :app:testDebugUnitTest 2>&1 | tail -20 && cd -
```

Expected: `BUILD SUCCESSFUL`. The full Android unit-test surface (not just crypto/pairing) catches anything that consumed the old v1 byte layout transitively.

- [ ] **Step 5: Tauri smoke test (optional but cheap)**

```bash
cargo test --manifest-path /Users/lieuwejongsma/SpeechToText/ui/src-tauri/Cargo.toml --release 2>&1 | tail -10
```

Expected: `test result: ok`. Tauri does not sign hub requests, so this just confirms the version bump didn't break the Rust build.

- [ ] **Step 6: Confirm git status is clean**

```bash
git status
```

Expected: `nothing to commit, working tree clean`. All work is on `main`, atomic per task.

---

## Acceptance (manual, batched hardware session — deferred per user preference)

Per the user's build-ahead, batch-device-test pattern, the following is **not** executed during this plan. Capture it as a follow-up session:

- Flash v2 firmware to the Waveshare ESP32-S3-ePaper board.
- Install the v2 Android APK.
- Start the v2 hub (`stt serve`).
- Confirm the demo silence-WAV upload returns 202 (firmware → hub stream-verify).
- Trigger an Android sync that hits `GET /sync/snapshot` — confirm 200.
- Smoke-test that an *old* (pre-v2) firmware build returns 401 against the v2 hub (proves the hard cut).
