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
