"""Tests for ``speechtotext.api.workspace`` identity persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from speechtotext.api import workspace


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "locallexis"


class TestWorkspaceId:
    def test_creates_on_first_call(self, config_dir: Path) -> None:
        wid = workspace.get_workspace_id(config_dir)
        assert wid.startswith("ws_")
        assert len(wid) > len("ws_")
        # File should now exist.
        assert (config_dir / "workspace.json").exists()

    def test_stable_across_calls(self, config_dir: Path) -> None:
        wid1 = workspace.get_workspace_id(config_dir)
        wid2 = workspace.get_workspace_id(config_dir)
        assert wid1 == wid2

    def test_different_dirs_give_different_ids(
        self, tmp_path: Path
    ) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        assert workspace.get_workspace_id(a) != workspace.get_workspace_id(b)


class TestDeviceId:
    def test_creates_on_first_call(self, config_dir: Path) -> None:
        did = workspace.get_device_id(config_dir)
        assert did.startswith("hub-")
        assert len(did) > len("hub-")

    def test_stable_across_calls(self, config_dir: Path) -> None:
        did1 = workspace.get_device_id(config_dir)
        did2 = workspace.get_device_id(config_dir)
        assert did1 == did2


class TestEnsureBoth:
    def test_calling_workspace_id_creates_device_id_too(
        self, config_dir: Path
    ) -> None:
        workspace.get_workspace_id(config_dir)
        data = json.loads(
            (config_dir / "workspace.json").read_text(encoding="utf-8")
        )
        assert "workspace_id" in data
        assert "device_id" in data

    def test_calling_device_id_creates_workspace_id_too(
        self, config_dir: Path
    ) -> None:
        workspace.get_device_id(config_dir)
        data = json.loads(
            (config_dir / "workspace.json").read_text(encoding="utf-8")
        )
        assert "workspace_id" in data
        assert "device_id" in data


class TestCorruption:
    def test_corrupt_file_regenerates(self, config_dir: Path) -> None:
        config_dir.mkdir(parents=True)
        (config_dir / "workspace.json").write_text("not valid json")
        wid = workspace.get_workspace_id(config_dir)
        assert wid.startswith("ws_")

    def test_partial_file_completed(self, config_dir: Path) -> None:
        config_dir.mkdir(parents=True)
        (config_dir / "workspace.json").write_text(
            json.dumps({"workspace_id": "ws_partial"})
        )
        # workspace_id stays the same; device_id added.
        wid = workspace.get_workspace_id(config_dir)
        did = workspace.get_device_id(config_dir)
        assert wid == "ws_partial"
        assert did.startswith("hub-")


class TestPath:
    def test_default_path_uses_app_data_dir(self) -> None:
        # Spot-check: default path lives under the platform app-data dir
        # (whatever that resolves to on the current OS).
        from speechtotext.api.library_db import default_app_data_dir

        assert (
            workspace.workspace_file_path()
            == default_app_data_dir() / "workspace.json"
        )

    def test_explicit_dir_honored(self, config_dir: Path) -> None:
        assert (
            workspace.workspace_file_path(config_dir)
            == config_dir / "workspace.json"
        )
