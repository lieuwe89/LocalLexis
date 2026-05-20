"""Device-signed request verification.

Wire protocol (v1)
------------------

Each request from a paired device carries two headers::

    X-Device-Id:     dev-<hex>
    X-Signature-B64: base64(Ed25519 signature)

The signature is computed over the message::

    HTTP_METHOD + "\\n" + PATH + "\\n" + raw_body_bytes

with the device's Ed25519 signing key. The hub looks the device up
by id, fetches the stored verify key, computes the same message, and
calls :meth:`nacl.signing.VerifyKey.verify`.

No replay protection (timestamp / nonce) yet — over HTTPS on the LAN
or Tailscale (the v1 deployment surface) that's acceptable. Block 5
defers a nonce table to v2 when remote reach opens up over the open
internet via WireGuard.

Failure modes
-------------

- Missing ``X-Device-Id`` or ``X-Signature-B64``: 401 + structured detail.
- Device id not in registry: 401 ``unknown device``.
- Signature does not verify: 401 ``signature verification failed``.

Side effects on success
-----------------------

- ``DeviceRegistry.update_last_seen`` is called.
- ``request.state.device_id`` is populated for downstream handlers.
"""

from __future__ import annotations

import base64

from fastapi import HTTPException, Request


async def verify_device_signature(request: Request) -> str:
    """FastAPI dependency. Returns the verified device_id.

    Usage::

        @router.patch(
            "/transcripts/{tid}",
            response_model=PatchResult,
        )
        def patch_transcript(
            tid: str,
            body: PatchOpBody,
            request: Request,
            device_id: str = Depends(verify_device_signature),
        ) -> PatchResult:
            ...
    """
    from nacl.exceptions import BadSignatureError
    from nacl.signing import VerifyKey

    device_id = request.headers.get("X-Device-Id")
    sig_b64 = request.headers.get("X-Signature-B64")
    if not device_id or not sig_b64:
        raise HTTPException(
            status_code=401,
            detail="missing X-Device-Id or X-Signature-B64 header",
        )

    registry = getattr(request.app.state, "device_registry", None)
    if registry is None:
        # Misconfiguration; surface clearly so deployers see it.
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

    body = await request.body()
    message = (
        request.method.encode("ascii")
        + b"\n"
        + request.url.path.encode("ascii")
        + b"\n"
        + body
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

    registry.update_last_seen(device_id)
    request.state.device_id = device_id
    return device_id
