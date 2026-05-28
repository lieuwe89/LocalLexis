"""Hub info endpoint — LAN address + TLS pin for composing the pairing QR.

Loopback-only by design. The desktop UI reaches the API over the
``127.0.0.1`` loopback socket and combines this response with a minted
pairing token + the hub port it already knows into a ``PairingPayloadV1``
QR. LAN devices hit the *same* FastAPI app on the HTTPS socket, so without
a gate they could enumerate the host's address + cert pin; non-loopback
clients therefore get 404.

The gate matters most when ``LOCALLEXIS_API_TOKEN`` is unset (``stt serve``
/ headless runs): the bearer middleware is disabled there, so this gate is
the only thing keeping the host's LAN address + SPKI off the open network.
Neither value is secret (the SPKI is a hash of the cert's public key, sent
on every TLS handshake; the LAN IP is locally discoverable), but
least-exposure is the right default.
"""

from __future__ import annotations

import os
import socket

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from speechtotext.api.tls import get_or_create_tls, spki_fingerprint_b64

router = APIRouter()

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
_TRUTHY = {"1", "true", "yes", "on"}


class HubInfo(BaseModel):
    lan_addresses: list[str]
    tls_enabled: bool
    tls_spki_b64: str | None


def _lan_addresses() -> list[str]:
    """Best-effort list of this host's non-loopback IPv4 addresses.

    The UDP-connect trick reveals the egress interface without sending a
    packet; ``getaddrinfo(hostname)`` picks up additional bound
    interfaces. Both are filtered for loopback / unspecified. May be empty
    (e.g. no network) — the caller surfaces that to the user.
    """
    addrs: set[str] = set()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # TEST-NET-3 (RFC 5737), never routed; no packet is actually sent.
            sock.connect(("203.0.113.1", 9))
            addrs.add(sock.getsockname()[0])
        finally:
            sock.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(
            socket.gethostname(), None, family=socket.AF_INET
        ):
            addrs.add(info[4][0])
    except OSError:
        pass
    return sorted(a for a in addrs if not a.startswith("127.") and a != "0.0.0.0")


@router.get("/hub/info", response_model=HubInfo)
def hub_info(request: Request) -> HubInfo:
    """LAN address(es) + TLS pin for the pairing QR. Loopback-only."""
    client_host = request.client.host if request.client else ""
    if client_host not in _LOOPBACK_HOSTS:
        # 404 (not 403) so the route's existence isn't advertised to LAN
        # scanners.
        raise HTTPException(status_code=404, detail="not found")

    tls_enabled = os.environ.get("LOCALLEXIS_TLS_ENABLED", "").strip().lower() in _TRUTHY
    spki: str | None = None
    if tls_enabled:
        cert_path, _ = get_or_create_tls()
        spki = spki_fingerprint_b64(cert_path.read_bytes())

    return HubInfo(
        lan_addresses=_lan_addresses(),
        tls_enabled=tls_enabled,
        tls_spki_b64=spki,
    )
