"""Tests for the headless server entry point (``server.headless``).

The function is small but the env-var contract is part of the public
deploy interface — Docker images, systemd units, and operators rely
on it. Cover the happy path and the only realistic misconfiguration
(non-integer port).
"""

from __future__ import annotations

import pytest

from speechtotext.api import server


@pytest.fixture
def fake_uvicorn(monkeypatch):
    """Replace ``uvicorn.run`` so the test doesn't actually start a server."""
    calls: list[dict] = []

    def fake_run(app, **kwargs):
        calls.append({"app": app, **kwargs})

    monkeypatch.setattr(server.uvicorn, "run", fake_run)
    return calls


class TestHeadless:
    def test_defaults_to_0_0_0_0_port_8765(
        self, fake_uvicorn, monkeypatch
    ) -> None:
        monkeypatch.delenv("LOCALLEXIS_HOST", raising=False)
        monkeypatch.delenv("LOCALLEXIS_PORT", raising=False)
        server.headless()
        assert len(fake_uvicorn) == 1
        call = fake_uvicorn[0]
        assert call["host"] == "0.0.0.0"
        assert call["port"] == 8765

    def test_env_overrides_host(self, fake_uvicorn, monkeypatch) -> None:
        monkeypatch.setenv("LOCALLEXIS_HOST", "127.0.0.1")
        monkeypatch.delenv("LOCALLEXIS_PORT", raising=False)
        server.headless()
        assert fake_uvicorn[0]["host"] == "127.0.0.1"

    def test_env_overrides_port(self, fake_uvicorn, monkeypatch) -> None:
        monkeypatch.delenv("LOCALLEXIS_HOST", raising=False)
        monkeypatch.setenv("LOCALLEXIS_PORT", "9999")
        server.headless()
        assert fake_uvicorn[0]["port"] == 9999

    def test_non_integer_port_exits_clearly(
        self, fake_uvicorn, monkeypatch
    ) -> None:
        monkeypatch.setenv("LOCALLEXIS_PORT", "not-a-number")
        with pytest.raises(SystemExit) as exc_info:
            server.headless()
        # Operator-readable message, not a bare traceback.
        assert "LOCALLEXIS_PORT" in str(exc_info.value)

    def test_no_handshake_to_stdout(
        self, fake_uvicorn, monkeypatch, capsys
    ) -> None:
        monkeypatch.delenv("LOCALLEXIS_HOST", raising=False)
        monkeypatch.delenv("LOCALLEXIS_PORT", raising=False)
        server.headless()
        captured = capsys.readouterr()
        assert "locallexis" not in captured.out
        assert "locallexis" not in captured.err


class TestRunBackwardsCompat:
    """The Tauri-spawned ``run`` entry must keep printing the handshake
    and binding 127.0.0.1; the sidecar lifecycle depends on it."""

    def test_run_still_prints_handshake(
        self, fake_uvicorn, capsys
    ) -> None:
        server.run(port=12345)
        captured = capsys.readouterr()
        assert '"port": 12345' in captured.out
        assert fake_uvicorn[0]["host"] == "127.0.0.1"
        assert fake_uvicorn[0]["port"] == 12345


class TestHeadlessTls:
    """LOCALLEXIS_TLS_ENABLED toggle drives uvicorn's ssl_* args."""

    def test_tls_disabled_by_default(self, fake_uvicorn, monkeypatch) -> None:
        for var in ("LOCALLEXIS_HOST", "LOCALLEXIS_PORT", "LOCALLEXIS_TLS_ENABLED"):
            monkeypatch.delenv(var, raising=False)
        server.headless()
        call = fake_uvicorn[0]
        assert "ssl_certfile" not in call
        assert "ssl_keyfile" not in call

    @pytest.mark.parametrize("flag", ["1", "true", "TRUE", "yes", "on"])
    def test_tls_enabled_resolves_cert_paths(
        self, fake_uvicorn, monkeypatch, tmp_path, flag
    ) -> None:
        monkeypatch.setenv("LOCALLEXIS_TLS_ENABLED", flag)
        monkeypatch.delenv("LOCALLEXIS_HOST", raising=False)
        monkeypatch.delenv("LOCALLEXIS_PORT", raising=False)
        # Redirect the tls module's app-data dir into the test tmp path
        # so we don't generate a real cert under the user's home.
        import speechtotext.api.tls as _tls

        monkeypatch.setattr(_tls, "default_app_data_dir", lambda: tmp_path)
        server.headless()
        call = fake_uvicorn[0]
        assert call["ssl_certfile"] == str(tmp_path / "hub-cert.pem")
        assert call["ssl_keyfile"] == str(tmp_path / "hub-key.pem")
        # Cert + key files were actually generated.
        assert (tmp_path / "hub-cert.pem").exists()
        assert (tmp_path / "hub-key.pem").exists()

    def test_tls_falsy_values_skip(
        self, fake_uvicorn, monkeypatch
    ) -> None:
        monkeypatch.setenv("LOCALLEXIS_TLS_ENABLED", "0")
        server.headless()
        assert "ssl_certfile" not in fake_uvicorn[0]


class TestHeadlessDualBind:
    """LOCALLEXIS_LOOPBACK_PORT + TLS triggers dual-bind for the Tauri
    webview, which cannot reach the self-signed HTTPS port directly.
    """

    @pytest.fixture
    def fake_dual_bind(self, monkeypatch):
        calls: list[dict] = []

        def fake(app, **kwargs):
            calls.append({"app": app, **kwargs})

        monkeypatch.setattr(server, "_run_dual_bind", fake)
        return calls

    def test_loopback_port_unset_uses_single_uvicorn(
        self, fake_uvicorn, fake_dual_bind, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setenv("LOCALLEXIS_TLS_ENABLED", "1")
        monkeypatch.delenv("LOCALLEXIS_LOOPBACK_PORT", raising=False)
        monkeypatch.delenv("LOCALLEXIS_HOST", raising=False)
        monkeypatch.delenv("LOCALLEXIS_PORT", raising=False)
        import speechtotext.api.tls as _tls

        monkeypatch.setattr(_tls, "default_app_data_dir", lambda: tmp_path)
        server.headless()
        assert fake_dual_bind == []
        assert len(fake_uvicorn) == 1

    def test_loopback_port_without_tls_falls_back_to_single(
        self, fake_uvicorn, fake_dual_bind, monkeypatch
    ) -> None:
        """No TLS = no need for dual-bind even if loopback is requested."""
        monkeypatch.delenv("LOCALLEXIS_TLS_ENABLED", raising=False)
        monkeypatch.setenv("LOCALLEXIS_LOOPBACK_PORT", "8766")
        monkeypatch.delenv("LOCALLEXIS_HOST", raising=False)
        monkeypatch.delenv("LOCALLEXIS_PORT", raising=False)
        server.headless()
        assert fake_dual_bind == []
        assert len(fake_uvicorn) == 1

    def test_dual_bind_when_tls_and_loopback(
        self, fake_uvicorn, fake_dual_bind, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setenv("LOCALLEXIS_TLS_ENABLED", "1")
        monkeypatch.setenv("LOCALLEXIS_LOOPBACK_PORT", "8766")
        monkeypatch.delenv("LOCALLEXIS_HOST", raising=False)
        monkeypatch.delenv("LOCALLEXIS_PORT", raising=False)
        import speechtotext.api.tls as _tls

        monkeypatch.setattr(_tls, "default_app_data_dir", lambda: tmp_path)
        server.headless()
        assert fake_uvicorn == [], "should NOT call uvicorn.run in dual-bind mode"
        assert len(fake_dual_bind) == 1
        call = fake_dual_bind[0]
        assert call["tls_host"] == "0.0.0.0"
        assert call["tls_port"] == 8765
        assert call["loopback_port"] == 8766
        assert call["cert_path"] == tmp_path / "hub-cert.pem"
        assert call["key_path"] == tmp_path / "hub-key.pem"

    def test_non_integer_loopback_port_exits_clearly(
        self, fake_uvicorn, monkeypatch
    ) -> None:
        monkeypatch.setenv("LOCALLEXIS_LOOPBACK_PORT", "nope")
        with pytest.raises(SystemExit) as exc:
            server.headless()
        assert "LOCALLEXIS_LOOPBACK_PORT" in str(exc.value)


class TestDualBindRunner:
    """The dual-bind helper builds two uvicorn configs and runs them
    concurrently; assert the shape of those configs without actually
    starting servers."""

    def test_builds_two_configs_with_right_args(
        self, monkeypatch, tmp_path
    ) -> None:
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        cert.write_text("")
        key.write_text("")

        config_calls: list[dict] = []

        class FakeConfig:
            def __init__(self, app, **kwargs):
                config_calls.append({"app": app, **kwargs})

        class FakeServer:
            def __init__(self, cfg):
                self.cfg = cfg

            async def serve(self):  # pragma: no cover - awaited below
                return None

        monkeypatch.setattr(server.uvicorn, "Config", FakeConfig)
        monkeypatch.setattr(server.uvicorn, "Server", FakeServer)

        # asyncio.run consumes the coroutine; let it run to completion
        # so the awaited gather actually fires the FakeServer.serve()
        # coroutines (otherwise we'd leak a "coroutine was never awaited"
        # warning).
        import asyncio

        ran: list[bool] = []

        def fake_run(coro):
            ran.append(True)
            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)

        monkeypatch.setattr(asyncio, "run", fake_run)

        sentinel_app = object()
        server._run_dual_bind(
            sentinel_app,
            tls_host="0.0.0.0",
            tls_port=8765,
            cert_path=cert,
            key_path=key,
            loopback_port=8766,
        )

        assert ran == [True]
        assert len(config_calls) == 2
        https_cfg = next(
            c for c in config_calls if "ssl_certfile" in c
        )
        loop_cfg = next(
            c for c in config_calls if "ssl_certfile" not in c
        )
        assert https_cfg["host"] == "0.0.0.0"
        assert https_cfg["port"] == 8765
        assert https_cfg["ssl_certfile"] == str(cert)
        assert https_cfg["ssl_keyfile"] == str(key)
        assert https_cfg["app"] is sentinel_app
        assert loop_cfg["host"] == "127.0.0.1"
        assert loop_cfg["port"] == 8766
        assert loop_cfg["lifespan"] == "off"
        assert loop_cfg["app"] is sentinel_app
