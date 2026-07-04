import base64
import json
import os

import httpx
import pytest
from nacl.public import SealedBox

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


def test_join_failure_rolls_back_identity():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid pairing token"})

    with pytest.raises(httpx.HTTPStatusError):
        join.join_hub(
            _payload_str(), device_name="x",
            transport=httpx.MockTransport(handler),
        )
    assert identity.load() is None
    assert state.load() is None


def test_leave_removes_identity_and_state():
    wkey = os.urandom(32)
    join.join_hub(
        _payload_str(), device_name="x",
        transport=_fake_hub_transport(wkey),
    )
    join.leave_hub()
    assert state.load() is None
    assert identity.load() is None
