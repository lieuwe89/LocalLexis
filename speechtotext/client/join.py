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
    if not isinstance(doc, dict):
        raise PairingStringError("payload is not a JSON object")
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
