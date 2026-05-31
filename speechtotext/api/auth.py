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

from __future__ import annotations

import base64
import threading
import time

from fastapi import HTTPException, Request

# Max clock skew between a signed request's timestamp and the hub. Doubles as
# the replay-cache retention window: a captured request is unusable once its
# timestamp ages past this, so nonces need only be remembered this long.
_SIGNATURE_WINDOW_S = 300.0


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


class NonceCache:
    """Sliding-window store of seen ``(device_id, nonce)`` pairs.

    Used to reject replays: a signed request whose nonce was already seen
    within the signature window is refused. Entries expire one window after
    insertion and are swept lazily on each check, so the cache stays bounded
    by the request rate over a single window.
    """

    def __init__(self, window_s: float = _SIGNATURE_WINDOW_S) -> None:
        self._window = window_s
        self._lock = threading.Lock()
        self._seen: dict[tuple[str, str], float] = {}

    def check_and_store(self, device_id: str, nonce: str) -> bool:
        """Return True if the pair is fresh (and record it); False if a replay."""
        now = time.time()
        key = (device_id, nonce)
        with self._lock:
            for k, exp in list(self._seen.items()):
                if exp <= now:
                    del self._seen[k]
            if key in self._seen:
                return False
            self._seen[key] = now + self._window
            return True


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
