from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "systemd"


def _unit(name):
    return (DEPLOY / name).read_text()


def test_hub_service_runs_headless_with_token_bind():
    u = _unit("locallexis-hub.service")
    assert "ExecStart=" in u
    assert "locallexis-hub serve" in u
    assert "LOCALLEXIS_PORT=8010" in u
    # 0.0.0.0 bind so lexis.lab.home.arpa (LAN) reaches /app; token required.
    assert "LOCALLEXIS_HOST=0.0.0.0" in u
    assert "EnvironmentFile=-/home/lieuwe/.config/speechtotext/service.env" in u
    assert "WorkingDirectory=/home/lieuwe/LocalLexis" in u
    assert "User=lieuwe" in u
    assert "WantedBy=multi-user.target" in u


def test_update_service_and_timer():
    svc = _unit("hub-update.service")
    assert "Type=oneshot" in svc
    assert "/home/lieuwe/LocalLexis/scripts/hub-update.sh" in svc
    assert "User=lieuwe" in svc
    # venv on PATH so bare `pip` in the script resolves to the venv pip.
    assert "Environment=PATH=/home/lieuwe/LocalLexis/.venv/bin:/usr/bin:/bin" in svc

    tmr = _unit("hub-update.timer")
    assert "OnCalendar=daily" in tmr
    assert "Persistent=true" in tmr
    assert "WantedBy=timers.target" in tmr
