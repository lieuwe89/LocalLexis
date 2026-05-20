"""Tests for ``speechtotext.api.secrets_store`` — workspace key W."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from speechtotext.api import secrets_store


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "locallexis"


class TestGetWorkspaceKey:
    def test_creates_on_first_call(self, config_dir: Path) -> None:
        key = secrets_store.get_workspace_key(config_dir)
        assert isinstance(key, bytes)
        assert len(key) == 32
        assert (config_dir / "secrets.bin").exists()

    def test_stable_across_calls(self, config_dir: Path) -> None:
        k1 = secrets_store.get_workspace_key(config_dir)
        k2 = secrets_store.get_workspace_key(config_dir)
        assert k1 == k2

    def test_different_dirs_give_different_keys(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        assert secrets_store.get_workspace_key(a) != secrets_store.get_workspace_key(b)

    def test_file_mode_is_0600(self, config_dir: Path) -> None:
        secrets_store.get_workspace_key(config_dir)
        path = config_dir / "secrets.bin"
        # On POSIX, mode bits below 0o777 are checked. mode & 0o777
        # masks off the file type so we can compare just the perms.
        mode = stat.S_IMODE(os.stat(path).st_mode)
        # Should be readable + writable by owner only.
        assert mode & 0o077 == 0, f"expected 0600-ish, got {oct(mode)}"
        assert mode & 0o600 == 0o600

    def test_truncated_file_regenerates(self, config_dir: Path) -> None:
        # Pre-populate with a too-short file.
        config_dir.mkdir(parents=True)
        (config_dir / "secrets.bin").write_bytes(b"short")
        key = secrets_store.get_workspace_key(config_dir)
        assert len(key) == 32

    def test_keys_are_random(self, tmp_path: Path) -> None:
        # Vanishingly unlikely two consecutive 32-byte tokens collide,
        # but check a few distinct dirs to be sure we are calling RNG.
        keys = {
            secrets_store.get_workspace_key(tmp_path / f"k{i}")
            for i in range(5)
        }
        assert len(keys) == 5


class TestPath:
    def test_default_path_uses_app_data_dir(self) -> None:
        from speechtotext.api.library_db import default_app_data_dir

        assert (
            secrets_store.secrets_file_path()
            == default_app_data_dir() / "secrets.bin"
        )

    def test_explicit_dir_honored(self, config_dir: Path) -> None:
        assert (
            secrets_store.secrets_file_path(config_dir)
            == config_dir / "secrets.bin"
        )
