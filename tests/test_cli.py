import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from speechtotext.cli import app

runner = CliRunner()


def test_help_lists_subcommands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for sub in ("transcribe", "record", "watch", "relabel", "config", "doctor"):
        assert sub in result.stdout


def test_transcribe_invokes_pipeline_and_writer(tmp_path: Path):
    audio = tmp_path / "in.mp3"
    audio.write_bytes(b"fake")

    pipeline_instance = MagicMock()
    pipeline_instance.run.return_value = MagicMock()

    with (
        patch("speechtotext.cli._build_pipeline", return_value=(pipeline_instance, "cpu")),
        patch("speechtotext.cli.write_transcript") as wt,
    ):
        result = runner.invoke(app, ["transcribe", str(audio), "--backend", "cpu"])

    assert result.exit_code == 0, result.stdout
    pipeline_instance.run.assert_called_once()
    wt.assert_called_once()


def test_transcribe_skips_when_sidecar_exists(tmp_path: Path):
    audio = tmp_path / "in.mp3"
    audio.write_bytes(b"fake")
    audio.with_suffix(".json").write_text("{}")
    with patch("speechtotext.cli._build_pipeline") as build:
        result = runner.invoke(app, ["transcribe", str(audio)])
    assert result.exit_code == 0
    assert "skipping" in result.stdout.lower()
    build.assert_not_called()


def test_relabel_invokes_module(tmp_path: Path):
    js = tmp_path / "rec.json"
    js.write_text("{}")
    with patch("speechtotext.cli.relabel_module.relabel") as rel:
        result = runner.invoke(
            app, ["relabel", str(js), "SPEAKER_00=Alice", "SPEAKER_01=Bob"]
        )
    assert result.exit_code == 0
    rel.assert_called_once_with(js, {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"})


def test_doctor_reports_status():
    with (
        patch("speechtotext.cli.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("speechtotext.cli.load_config") as lc,
    ):
        cfg = MagicMock()
        cfg.hf_token = "hf_x"
        cfg.model_cache_dir = Path("/tmp")
        cfg.backend = "cpu"
        lc.return_value = cfg
        result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "ffmpeg" in result.stdout.lower()
