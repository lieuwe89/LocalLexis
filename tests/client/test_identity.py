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
