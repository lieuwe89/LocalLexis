"""Self-signed TLS cert + key for the hub.

When the user enables hub mode (block 4), the sidecar binds to a LAN-
reachable interface and must serve HTTPS so paired devices can pin
the hub's identity. We generate a self-signed certificate on first
hub-mode enablement and persist it under the app-data dir; subsequent
toggles reuse it. The cert is valid for 10 years — devices pin the
SPKI fingerprint via the pairing QR, so any rotation forces
re-pairing and should be a deliberate user action, not a timer.

The cert SAN covers ``localhost``, ``127.0.0.1``, and ``0.0.0.0`` so
LAN clients reaching the hub via its IP get a matching certificate.
Mobile clients should pin the SPKI fingerprint (returned in the
pairing QR) rather than rely on hostname matching, since the hub's
LAN IP may change.

Storage layout::

    <app-data>/hub-cert.pem  (mode 0644)
    <app-data>/hub-key.pem   (mode 0600)

The private key never travels off-host; only the cert SPKI hash is
distributed via pairing.
"""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from speechtotext.api.library_db import default_app_data_dir

CERT_FILENAME = "hub-cert.pem"
KEY_FILENAME = "hub-key.pem"
_VALIDITY_DAYS = 365 * 10  # 10 years; pinned, manual rotation only


def tls_paths(config_dir: Path | None = None) -> tuple[Path, Path]:
    """Return ``(cert_path, key_path)`` under the platform app-data dir.

    Pass ``config_dir`` in tests to redirect away from the user's
    real config directory.
    """
    base = Path(config_dir) if config_dir else default_app_data_dir()
    return base / CERT_FILENAME, base / KEY_FILENAME


def _build_cert(key: rsa.RSAPrivateKey) -> x509.Certificate:
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "LocalLexis Hub"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "LocalLexis"),
        ]
    )
    now = datetime.now(timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        # 1-minute backdate forgives small clock skew on the verifier.
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=_VALIDITY_DAYS))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ip_address("127.0.0.1")),
                    x509.IPAddress(ip_address("0.0.0.0")),
                ]
            ),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .sign(private_key=key, algorithm=hashes.SHA256())
    )


def _write_pem_atomic(path: Path, data: bytes, *, mode: int) -> None:
    """Atomic tmp-then-rename write with explicit POSIX mode bits.

    Used for both cert (0644) and key (0600). The mode is applied to
    the *tmp* file before the rename so the bytes are never visible
    at the wider mode in the destination path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _generate(cert_path: Path, key_path: Path) -> None:
    """Generate a fresh RSA-2048 keypair + self-signed cert."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = _build_cert(key)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    _write_pem_atomic(key_path, key_pem, mode=0o600)
    _write_pem_atomic(cert_path, cert_pem, mode=0o644)


def get_or_create_tls(config_dir: Path | None = None) -> tuple[Path, Path]:
    """Return ``(cert_path, key_path)``, generating on first call.

    If *either* file is missing, both are regenerated — a cert
    without its key (or vice versa) is unusable and rotating both is
    the only sane recovery. Paired devices then need to re-pair,
    which matches the documented "delete the secrets file" recovery
    flow.
    """
    cert_path, key_path = tls_paths(config_dir)
    if not (cert_path.exists() and key_path.exists()):
        _generate(cert_path, key_path)
    return cert_path, key_path


def spki_fingerprint_hex(cert_pem_bytes: bytes) -> str:
    """SHA-256 hex of the cert's SubjectPublicKeyInfo (SPKI).

    Devices pin this value via the pairing QR and verify the
    certificate they receive over TLS matches before trusting the
    connection. Pinning SPKI rather than the whole cert means a key
    rotation forces re-pair, but a cosmetic re-issue with the same
    key (different validity dates, different SAN) does not.
    """
    cert = x509.load_pem_x509_certificate(cert_pem_bytes)
    spki = cert.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(spki).hexdigest()


def spki_fingerprint_b64(cert_pem_bytes: bytes) -> str:
    """Base64 of the SHA-256 SPKI digest — the OkHttp ``CertificatePinner``
    pin body. The pairing QR carries this value; the mobile client pins
    ``sha256/<value>``. Same digest as :func:`spki_fingerprint_hex`,
    base64-encoded instead of hex.
    """
    cert = x509.load_pem_x509_certificate(cert_pem_bytes)
    spki = cert.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(hashlib.sha256(spki).digest()).decode("ascii")
