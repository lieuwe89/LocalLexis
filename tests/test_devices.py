import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from speechtotext.cli import app
from speechtotext.devices import AudioDevice, classify, list_inputs


def _fake_query(devices: list[dict]):
    def _q(*args, **kwargs):
        if args or kwargs:  # query a specific device — unused here
            return devices[args[0]]
        return devices
    return _q


@pytest.fixture
def fixture_devices() -> list[dict]:
    return [
        {
            "name": "MacBook Pro Microphone",
            "max_input_channels": 1,
            "max_output_channels": 0,
            "default_samplerate": 48000.0,
        },
        {
            "name": "MacBook Pro Speakers",
            "max_input_channels": 0,
            "max_output_channels": 2,
            "default_samplerate": 48000.0,
        },
        {
            "name": "BlackHole 2ch",
            "max_input_channels": 2,
            "max_output_channels": 2,
            "default_samplerate": 48000.0,
        },
    ]


def test_lists_only_input_devices_by_default(fixture_devices):
    with (
        patch("speechtotext.devices.sd.query_devices", side_effect=_fake_query(fixture_devices)),
        patch("speechtotext.devices.sd.default") as default,
    ):
        default.device = (0, 1)
        result = list_inputs()
    assert [d.name for d in result] == ["MacBook Pro Microphone", "BlackHole 2ch"]


def test_include_all_returns_everything(fixture_devices):
    with (
        patch("speechtotext.devices.sd.query_devices", side_effect=_fake_query(fixture_devices)),
        patch("speechtotext.devices.sd.default") as default,
    ):
        default.device = (0, 1)
        result = list_inputs(include_all=True)
    assert len(result) == 3


def test_default_flag_set_on_default_device(fixture_devices):
    with (
        patch("speechtotext.devices.sd.query_devices", side_effect=_fake_query(fixture_devices)),
        patch("speechtotext.devices.sd.default") as default,
    ):
        default.device = (2, 1)  # index 2 = BlackHole as default input
        result = list_inputs()
    by_name = {d.name: d for d in result}
    assert by_name["BlackHole 2ch"].default is True
    assert by_name["MacBook Pro Microphone"].default is False


def test_default_when_sd_default_is_scalar(fixture_devices):
    with (
        patch("speechtotext.devices.sd.query_devices", side_effect=_fake_query(fixture_devices)),
        patch("speechtotext.devices.sd.default") as default,
    ):
        default.device = 0  # some hostapis return a scalar, not a tuple
        result = list_inputs()
    assert [d.default for d in result if d.name == "MacBook Pro Microphone"] == [True]


@pytest.mark.parametrize(
    "name,expected",
    [
        ("MacBook Pro Microphone", "mic"),
        ("External USB Mic", "mic"),
        ("AirPods Pro", "mic"),
        ("BlackHole 2ch", "loopback"),
        ("Soundflower (2ch)", "loopback"),
        ("VoiceMeeter Output", "loopback"),
        ("Monitor of Built-in Audio Analog Stereo", "loopback"),
        ("Some Random Stereo Mix Device", "loopback"),
        ("Aggregate (Mic + BlackHole)", "mic+loopback"),
        ("Some Weird DAC Thing", "unknown"),
    ],
)
def test_hint_classification(name, expected):
    assert classify(name) == expected


def test_audio_device_is_frozen():
    d = AudioDevice(index=0, name="x", channels=1, sample_rate=48000.0, default=False, hint="mic")
    with pytest.raises(Exception):
        d.name = "y"  # frozen dataclass — must raise


def test_cli_table_output(fixture_devices):
    runner = CliRunner()
    with (
        patch("speechtotext.devices.sd.query_devices", side_effect=_fake_query(fixture_devices)),
        patch("speechtotext.devices.sd.default") as default,
    ):
        default.device = (0, 1)
        result = runner.invoke(app, ["devices"])
    assert result.exit_code == 0
    assert "MacBook Pro Microphone" in result.stdout
    assert "BlackHole 2ch" in result.stdout


def test_cli_json_output(fixture_devices):
    runner = CliRunner()
    with (
        patch("speechtotext.devices.sd.query_devices", side_effect=_fake_query(fixture_devices)),
        patch("speechtotext.devices.sd.default") as default,
    ):
        default.device = (0, 1)
        result = runner.invoke(app, ["devices", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    names = [d["name"] for d in payload]
    assert "MacBook Pro Microphone" in names
    assert all(set(d.keys()) >= {"index", "name", "channels", "sample_rate", "default", "hint"} for d in payload)


def test_cli_exit_1_when_no_inputs():
    runner = CliRunner()
    with (
        patch("speechtotext.devices.sd.query_devices", side_effect=_fake_query([])),
        patch("speechtotext.devices.sd.default") as default,
    ):
        default.device = (0, 1)
        result = runner.invoke(app, ["devices"])
    assert result.exit_code == 1
    assert "stt doctor" in (result.stderr or "") + result.stdout
