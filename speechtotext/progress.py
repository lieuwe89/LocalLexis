from __future__ import annotations

import json
import sys
from typing import Callable

from rich.console import Console

from speechtotext.models import ProgressEvent

_console = Console(stderr=True)


def console_renderer(quiet: bool = False) -> Callable[[ProgressEvent], None]:
    def _emit(event: ProgressEvent) -> None:
        if quiet:
            return
        _console.log(f"[{event.stage}] {int(event.pct * 100):3d}% {event.message}")
    return _emit


def json_renderer() -> Callable[[ProgressEvent], None]:
    def _emit(event: ProgressEvent) -> None:
        sys.stderr.write(
            json.dumps(
                {"stage": event.stage, "pct": event.pct, "message": event.message}
            )
            + "\n"
        )
        sys.stderr.flush()
    return _emit
