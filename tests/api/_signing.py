"""Shared helper for signing device requests in tests.

Centralised so the wire scheme (method + path?query + timestamp + nonce +
body) lives in one place: the server's ``build_signed_message`` is the source
of truth and tests sign with the exact same function.
"""

from __future__ import annotations

import base64
import secrets
import time

from speechtotext.api.auth import build_signed_message


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
