from __future__ import annotations

import json
import os
import socket
import sys

import uvicorn

from speechtotext.api.app import create_app


def pick_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def run(host: str = "127.0.0.1", port: int | None = None, print_handshake: bool = True) -> None:
    """Tauri-spawned sidecar entry: localhost, random port, JSON handshake on stdout."""
    p = port or pick_port()
    if print_handshake:
        sys.stdout.write(json.dumps({"locallexis": {"host": host, "port": p}}) + "\n")
        sys.stdout.flush()
    uvicorn.run(create_app(), host=host, port=p, log_level="warning")


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int | None = None) -> int | None:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer, got {raw!r}: {exc}")


def _run_dual_bind(
    app,
    *,
    tls_host: str,
    tls_port: int,
    cert_path,
    key_path,
    loopback_port: int,
) -> None:
    """Serve HTTPS on the LAN socket and plaintext HTTP on 127.0.0.1.

    The Tauri webview cannot reach the self-signed HTTPS port (WebKit /
    WebView2 reject the cert), but LAN devices can pin the SPKI via the
    pairing QR. Running both bindings against the same FastAPI app lets
    the desktop UI keep using ``fetch()`` against the loopback socket
    while phones / tablets dial in over HTTPS.

    Lifespan stays enabled only on the HTTPS server so startup hooks
    (microphone warmup, library reconcile) fire exactly once.
    """
    import asyncio

    tls_cfg = uvicorn.Config(
        app,
        host=tls_host,
        port=tls_port,
        log_level="info",
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
    )
    loop_cfg = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=loopback_port,
        log_level="info",
        lifespan="off",
    )
    tls_server = uvicorn.Server(tls_cfg)
    loop_server = uvicorn.Server(loop_cfg)

    async def _serve_both() -> None:
        await asyncio.gather(tls_server.serve(), loop_server.serve())

    asyncio.run(_serve_both())


def headless() -> None:
    """Standalone hub entry: binds 0.0.0.0 on a stable port.

    Used by the headless deployment (Docker image, systemd unit, NAS /
    VPS install) and by the Tauri shell when "hub mode" is on.

    Defaults:

    - host:          ``0.0.0.0``  (override via ``LOCALLEXIS_HOST``)
    - port:          ``8765``     (override via ``LOCALLEXIS_PORT``)
    - tls:           off          (enable via ``LOCALLEXIS_TLS_ENABLED=1``)
    - loopback port: unset        (set via ``LOCALLEXIS_LOOPBACK_PORT``)

    When ``LOCALLEXIS_TLS_ENABLED`` is truthy, the sidecar serves HTTPS
    using the self-signed cert at ``<app-data>/hub-cert.pem`` (auto-
    generated on first call). Mobile clients are expected to pin the
    cert's SPKI fingerprint via the pairing QR rather than rely on
    hostname matching.

    When ``LOCALLEXIS_LOOPBACK_PORT`` is set *and* TLS is enabled, the
    sidecar additionally binds plain HTTP on ``127.0.0.1:<that port>``
    so the Tauri webview can reach the API without fighting the self-
    signed cert. Pure headless deploys (Docker, systemd) leave it unset.

    No stdout handshake — the Tauri shell uses ``run`` for the
    localhost sidecar lifecycle that needs the handshake; ``headless``
    is the LAN/server entry.
    """
    host = os.environ.get("LOCALLEXIS_HOST", "0.0.0.0")
    port = _int_env("LOCALLEXIS_PORT", 8765)
    loopback_port = _int_env("LOCALLEXIS_LOOPBACK_PORT")
    tls = _env_truthy("LOCALLEXIS_TLS_ENABLED")
    app = create_app()

    if tls and loopback_port is not None:
        # Lazy import so non-TLS callers don't pay the cryptography
        # import cost (and tests can monkeypatch the resolver).
        from speechtotext.api.tls import get_or_create_tls

        cert_path, key_path = get_or_create_tls()
        _run_dual_bind(
            app,
            tls_host=host,
            tls_port=port,
            cert_path=cert_path,
            key_path=key_path,
            loopback_port=loopback_port,
        )
        return

    kwargs: dict = {"host": host, "port": port, "log_level": "info"}
    if tls:
        from speechtotext.api.tls import get_or_create_tls

        cert_path, key_path = get_or_create_tls()
        kwargs["ssl_certfile"] = str(cert_path)
        kwargs["ssl_keyfile"] = str(key_path)

    uvicorn.run(app, **kwargs)
