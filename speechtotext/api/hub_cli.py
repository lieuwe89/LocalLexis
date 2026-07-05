"""Console entry for ``locallexis-hub``.

``locallexis-hub``            -> headless server (unchanged default behavior)
``locallexis-hub serve``      -> same, explicit
``locallexis-hub pair``       -> mint a pairing token via the loopback API
                                 and print the pairing string (+ ASCII QR).

``pair`` exists for headless installs where there is no desktop UI to
compose the QR. It talks to the *running* hub over loopback using the
admin bearer token from LOCALLEXIS_API_TOKEN.
"""

from __future__ import annotations

import base64
import json
import os

import typer

app = typer.Typer(
    no_args_is_help=False,
    invoke_without_command=True,
    help="LocalLexis headless hub.",
)


@app.callback()
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        serve()


@app.command()
def serve() -> None:
    """Run the headless hub server (default when no subcommand given)."""
    from speechtotext.api.server import headless

    headless()


def _mint_token(loopback_url: str, admin_token: str) -> dict:
    import httpx

    resp = httpx.post(
        f"{loopback_url}/pair/tokens",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()


@app.command()
def pair(
    url: str = typer.Option(
        ...,
        "--url",
        help=(
            "Hub URL as DEVICES reach it, e.g. http://hub.tailnet:8010. "
            "Goes into the pairing payload verbatim."
        ),
    ),
    note: str = typer.Option(
        "", "--note", help="Optional note printed alongside the token."
    ),
    qr: bool = typer.Option(True, "--qr/--no-qr", help="Print an ASCII QR."),
) -> None:
    """Mint a single-use pairing token and print the pairing string."""
    admin_token = os.environ.get("LOCALLEXIS_API_TOKEN", "").strip()
    if not admin_token:
        typer.echo(
            "LOCALLEXIS_API_TOKEN is not set — the pair command talks to "
            "the running hub over loopback and needs the admin token.",
            err=True,
        )
        raise typer.Exit(code=2)
    port = os.environ.get("LOCALLEXIS_PORT", "8765").strip()
    loopback = f"http://127.0.0.1:{port}"

    minted = _mint_token(loopback, admin_token)
    payload = {
        "hub_url": url.rstrip("/"),
        "workspace_id": minted["workspace_id"],
        "token": minted["token"],
    }
    pairing_string = base64.b64encode(
        json.dumps(payload).encode("utf-8")
    ).decode("ascii")

    typer.echo(f"Pairing token minted (valid {minted['ttl_seconds']}s).")
    if note:
        typer.echo(f"Note: {note}")
    if qr:
        try:
            import qrcode

            q = qrcode.QRCode(border=1)
            q.add_data(json.dumps(payload))
            q.make(fit=True)
            q.print_ascii(invert=True)
        except ImportError:
            typer.echo("(install 'qrcode' for an ASCII QR)", err=True)
    typer.echo("Paste this into the desktop app's 'Join a hub' field:")
    typer.echo("")
    typer.echo(pairing_string)


def main() -> None:
    app()
