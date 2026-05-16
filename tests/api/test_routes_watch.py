import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from speechtotext.api.app import create_app


def test_watch_start_and_stop(tmp_path: Path):
    app = create_app()
    client = TestClient(app)
    with patch("speechtotext.api.watcher.run_watch") as rw:
        rw.side_effect = lambda **kw: kw["stop_event"].wait()  # blocks until stop
        r = client.post("/watch/start", json={"directory": str(tmp_path)})
        assert r.status_code == 200
        assert client.get("/watch/status").json()["running"] is True
        r2 = client.post("/watch/stop")
        assert r2.status_code == 200
        time.sleep(0.05)
        assert client.get("/watch/status").json()["running"] is False
