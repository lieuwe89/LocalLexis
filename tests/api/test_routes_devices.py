from dataclasses import asdict
from unittest.mock import patch

from fastapi.testclient import TestClient

from speechtotext.api.app import create_app
from speechtotext.devices import AudioDevice


def test_devices_endpoint_returns_inputs():
    fake = [AudioDevice(index=0, name="MacBook Mic", channels=1,
                        sample_rate=48000.0, default=True, hint="mic")]
    with patch("speechtotext.api.routes_devices.list_inputs", return_value=fake):
        app = create_app()
        r = TestClient(app).get("/devices")
        assert r.status_code == 200
        assert r.json() == [asdict(fake[0])]
