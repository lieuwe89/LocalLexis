from __future__ import annotations

import json
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
    p = port or pick_port()
    if print_handshake:
        sys.stdout.write(json.dumps({"localscribe": {"host": host, "port": p}}) + "\n")
        sys.stdout.flush()
    uvicorn.run(create_app(), host=host, port=p, log_level="warning")
