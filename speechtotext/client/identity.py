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
