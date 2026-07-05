import base64
import json

from typer.testing import CliRunner

from speechtotext.api import hub_cli

runner = CliRunner()


def test_pair_prints_pairing_string(monkeypatch):
    def fake_mint(url, token):
        assert url == "http://127.0.0.1:8010"
        assert token == "admintok"
        return {"token": "PAIRTOK", "workspace_id": "ws-1",
                "expires_at": 0, "ttl_seconds": 300}

    monkeypatch.setattr(hub_cli, "_mint_token", fake_mint)
    monkeypatch.setenv("LOCALLEXIS_API_TOKEN", "admintok")
    monkeypatch.setenv("LOCALLEXIS_PORT", "8010")

    result = runner.invoke(
        hub_cli.app, ["pair", "--url", "http://hub.tailnet:8010", "--no-qr"]
    )
    assert result.exit_code == 0, result.output
    line = [l for l in result.output.splitlines() if l.strip()][-1]
    payload = json.loads(base64.b64decode(line.strip()))
    assert payload == {
        "hub_url": "http://hub.tailnet:8010",
        "workspace_id": "ws-1",
        "token": "PAIRTOK",
    }


def test_pair_requires_admin_token(monkeypatch):
    monkeypatch.delenv("LOCALLEXIS_API_TOKEN", raising=False)
    result = runner.invoke(
        hub_cli.app, ["pair", "--url", "http://hub:8010", "--no-qr"]
    )
    assert result.exit_code != 0
    assert "LOCALLEXIS_API_TOKEN" in result.output


def test_pair_strips_trailing_slash_in_hub_url(monkeypatch):
    monkeypatch.setattr(hub_cli, "_mint_token", lambda url, token: {
        "token": "T", "workspace_id": "W", "expires_at": 0, "ttl_seconds": 300})
    monkeypatch.setenv("LOCALLEXIS_API_TOKEN", "a")
    result = runner.invoke(
        hub_cli.app, ["pair", "--url", "http://hub:8010/", "--no-qr"])
    assert result.exit_code == 0, result.output
    line = [l for l in result.output.splitlines() if l.strip()][-1]
    payload = json.loads(base64.b64decode(line.strip()))
    assert payload["hub_url"] == "http://hub:8010"  # no trailing slash


def test_default_invocation_would_serve(monkeypatch):
    """Bare `locallexis-hub` (no subcommand) routes to the headless server.
    We don't actually boot it — just assert the callback calls serve()."""
    called = {}
    monkeypatch.setattr(hub_cli, "serve", lambda: called.setdefault("serve", True))
    result = runner.invoke(hub_cli.app, [])
    assert called.get("serve") is True
