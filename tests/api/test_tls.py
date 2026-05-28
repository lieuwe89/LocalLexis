"""Tests for ``speechtotext.api.tls`` — self-signed cert generation."""

from __future__ import annotations

import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from speechtotext.api import tls


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "locallexis"


class TestGetOrCreateTls:
    def test_creates_both_files(self, config_dir: Path) -> None:
        cert, key = tls.get_or_create_tls(config_dir)
        assert cert.exists()
        assert key.exists()
        assert cert.name == "hub-cert.pem"
        assert key.name == "hub-key.pem"

    def test_stable_across_calls(self, config_dir: Path) -> None:
        cert1, key1 = tls.get_or_create_tls(config_dir)
        cert_bytes_1 = cert1.read_bytes()
        cert2, key2 = tls.get_or_create_tls(config_dir)
        cert_bytes_2 = cert2.read_bytes()
        # Same paths AND same bytes — no regen on second call.
        assert cert1 == cert2
        assert key1 == key2
        assert cert_bytes_1 == cert_bytes_2

    @pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits not enforced on Windows")
    def test_key_mode_is_0600(self, config_dir: Path) -> None:
        _, key = tls.get_or_create_tls(config_dir)
        mode = stat.S_IMODE(os.stat(key).st_mode)
        assert mode & 0o077 == 0
        assert mode & 0o600 == 0o600

    def test_cert_mode_is_readable(self, config_dir: Path) -> None:
        cert, _ = tls.get_or_create_tls(config_dir)
        mode = stat.S_IMODE(os.stat(cert).st_mode)
        # 0644 — readable by world so anyone trying to verify can read.
        assert mode & 0o400, f"cert should be owner-readable, got {oct(mode)}"

    def test_regenerates_when_key_missing(self, config_dir: Path) -> None:
        cert, key = tls.get_or_create_tls(config_dir)
        cert_bytes_before = cert.read_bytes()
        key.unlink()
        cert2, key2 = tls.get_or_create_tls(config_dir)
        # Both files now present again with fresh content.
        assert key2.exists()
        assert cert2.read_bytes() != cert_bytes_before

    def test_regenerates_when_cert_missing(self, config_dir: Path) -> None:
        cert, key = tls.get_or_create_tls(config_dir)
        key_bytes_before = key.read_bytes()
        cert.unlink()
        cert2, key2 = tls.get_or_create_tls(config_dir)
        assert cert2.exists()
        assert key2.read_bytes() != key_bytes_before


class TestCertContents:
    def test_cert_is_valid_x509(self, config_dir: Path) -> None:
        from cryptography import x509

        cert_path, _ = tls.get_or_create_tls(config_dir)
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        # Just exercise enough fields to confirm it parsed.
        assert cert.not_valid_before_utc < datetime.now(timezone.utc)
        assert cert.not_valid_after_utc > datetime.now(timezone.utc) + timedelta(days=365 * 5)

    def test_cert_includes_san(self, config_dir: Path) -> None:
        from cryptography import x509
        from cryptography.x509.oid import ExtensionOID

        cert_path, _ = tls.get_or_create_tls(config_dir)
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san = cert.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        ).value
        dns_names = [n.value for n in san if hasattr(n, "value") and isinstance(n, x509.DNSName)]
        assert "localhost" in dns_names

    def test_cert_basic_constraints_not_ca(self, config_dir: Path) -> None:
        from cryptography import x509
        from cryptography.x509.oid import ExtensionOID

        cert_path, _ = tls.get_or_create_tls(config_dir)
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        bc = cert.extensions.get_extension_for_oid(
            ExtensionOID.BASIC_CONSTRAINTS
        ).value
        assert bc.ca is False


class TestSpkiFingerprint:
    def test_stable_for_same_cert(self, config_dir: Path) -> None:
        cert_path, _ = tls.get_or_create_tls(config_dir)
        cert_bytes = cert_path.read_bytes()
        fp1 = tls.spki_fingerprint_hex(cert_bytes)
        fp2 = tls.spki_fingerprint_hex(cert_bytes)
        assert fp1 == fp2
        assert len(fp1) == 64  # sha256 hex

    def test_differs_for_different_certs(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        cert_a, _ = tls.get_or_create_tls(a)
        cert_b, _ = tls.get_or_create_tls(b)
        fp_a = tls.spki_fingerprint_hex(cert_a.read_bytes())
        fp_b = tls.spki_fingerprint_hex(cert_b.read_bytes())
        assert fp_a != fp_b

    def test_b64_matches_hex_digest(self, config_dir: Path) -> None:
        # tls_spki_b64 must be base64 of the *same* SHA-256 SPKI digest the
        # hex helper returns — this is the value the pairing QR carries and
        # Android pins as ``sha256/<value>`` (OkHttp CertificatePinner).
        # Lock the encoding so it can't silently drift.
        import base64

        cert_path, _ = tls.get_or_create_tls(config_dir)
        cert_bytes = cert_path.read_bytes()
        b64 = tls.spki_fingerprint_b64(cert_bytes)
        decoded = base64.b64decode(b64)
        assert decoded == bytes.fromhex(tls.spki_fingerprint_hex(cert_bytes))
        assert len(decoded) == 32  # sha256


class TestPath:
    def test_default_paths_under_app_data_dir(self) -> None:
        # `import X as Y` resolves through sys.modules (which the
        # conftest autouse fixture monkeypatches) instead of walking
        # the parent attribute. The latter is unreliable across tests
        # that wipe sys.modules (test_sidecar_cold_start); see the
        # comment in tests/api/conftest.py for the full story.
        import speechtotext.api.tls as _tls

        cert, key = _tls.tls_paths()
        base = _tls.default_app_data_dir()
        assert cert == base / "hub-cert.pem"
        assert key == base / "hub-key.pem"

    def test_explicit_dir_honored(self, config_dir: Path) -> None:
        cert, key = tls.tls_paths(config_dir)
        assert cert == config_dir / "hub-cert.pem"
        assert key == config_dir / "hub-key.pem"
