"""Pairing endpoints — token mint + device pair exchange.

See :mod:`speechtotext.api.pairing` for the protocol summary. These
endpoints sit at the network surface; the actual token bookkeeping
lives in :class:`PairingTokenStore` attached to ``app.state``.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from speechtotext.api.pairing import (
    PairingTokenStore,
    TOKEN_TTL_SECONDS,
    new_device_id,
)
from speechtotext.api.secrets_store import get_workspace_key
from speechtotext.api.workspace import get_lamport, get_workspace_id

router = APIRouter()


class MintTokenResponse(BaseModel):
    """Hub UI receives this after ``POST /pair/tokens``."""

    token: str
    expires_at: float = Field(
        description="Unix epoch seconds when the token stops being valid.",
    )
    workspace_id: str
    ttl_seconds: int


class PairRequest(BaseModel):
    """Device → hub during the pairing exchange."""

    token: str = Field(min_length=1)
    device_pubkey_b64: str = Field(
        description="32-byte Ed25519 verify key, base64-encoded.",
        min_length=1,
    )
    device_name: str = Field(min_length=1, max_length=128)


class PairResponse(BaseModel):
    """Hub → device after a successful pairing."""

    device_id: str
    workspace_id: str
    workspace_key_sealed_b64: str = Field(
        description=(
            "libsodium SealedBox(W) encrypted to the device's Curve25519 "
            "public key (derived from its Ed25519 verify key). "
            "Base64-encoded."
        )
    )
    lamport_observed: int = Field(
        description="Hub's current Lamport. Device should start from here.",
    )


def _store(request: Request) -> PairingTokenStore:
    return request.app.state.pairing_tokens


@router.post("/pair/tokens", response_model=MintTokenResponse)
def mint_pairing_token(request: Request) -> MintTokenResponse:
    """Mint a single-use pairing token.

    Intended to be called by the hub's local UI (Tauri desktop app or
    headless admin), which then renders the token as a QR code for a
    new device to scan. In v1 there is no admin auth here — anyone
    able to reach the hub's API can mint a token. Block 5c's
    signed-request middleware does not gate this endpoint because
    pairing is the bootstrap; future hardening may add a one-time
    local admin secret.
    """
    tok = _store(request).mint()
    return MintTokenResponse(
        token=tok.token,
        expires_at=tok.created_at + TOKEN_TTL_SECONDS,
        workspace_id=get_workspace_id(),
        ttl_seconds=TOKEN_TTL_SECONDS,
    )


@router.post("/pair", response_model=PairResponse)
def pair_device(req: PairRequest, request: Request) -> PairResponse:
    """Consume a pairing token and return a sealedbox of the workspace key.

    Failure modes:
    - 401: token unknown / consumed / expired (no information leaked
      about which; clients re-request a fresh token).
    - 400: device_pubkey_b64 fails to decode or is not a valid 32-byte
      Ed25519 verify key.
    """
    # Lazy import so importing this router does not pull libsodium
    # into the cold-start path of every other API consumer.
    from nacl.public import SealedBox
    from nacl.signing import VerifyKey

    try:
        _store(request).consume(req.token)
    except ValueError:
        # Don't disambiguate failure reasons across the network — every
        # bad token looks the same to a client.
        raise HTTPException(status_code=401, detail="invalid pairing token")

    try:
        pubkey_raw = base64.b64decode(req.device_pubkey_b64, validate=True)
    except Exception as exc:  # base64 decoding has a few exception flavours
        raise HTTPException(
            status_code=400, detail=f"device_pubkey_b64 not valid base64: {exc}"
        )
    if len(pubkey_raw) != 32:
        raise HTTPException(
            status_code=400,
            detail=(
                f"device pubkey must be 32 bytes (Ed25519), got "
                f"{len(pubkey_raw)}"
            ),
        )

    try:
        verify_key = VerifyKey(pubkey_raw)
        curve_pubkey = verify_key.to_curve25519_public_key()
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"invalid Ed25519 pubkey: {exc}"
        )

    workspace_key = get_workspace_key()
    sealed = SealedBox(curve_pubkey).encrypt(workspace_key)

    # device_id is hub-assigned. Persist the pubkey + name so the
    # subsequent signed-request middleware can verify the device.
    device_id = new_device_id()
    request.app.state.device_registry.register(
        device_id=device_id,
        pubkey_b64=req.device_pubkey_b64,
        name=req.device_name,
    )

    return PairResponse(
        device_id=device_id,
        workspace_id=get_workspace_id(),
        workspace_key_sealed_b64=base64.b64encode(sealed).decode("ascii"),
        lamport_observed=get_lamport(),
    )
