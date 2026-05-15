from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class StageEvent:
    type: Literal["stage"] = "stage"
    stage: str = ""
    percent: float = 0.0


@dataclass(frozen=True)
class LineEvent:
    type: Literal["line"] = "line"
    speaker: str = ""
    ts: float = 0.0
    text: str = ""


@dataclass(frozen=True)
class CompleteEvent:
    type: Literal["complete"] = "complete"
    transcript_id: str = ""
    paths: dict[str, str] = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ErrorEvent:
    type: Literal["error"] = "error"
    message: str = ""


JobEvent = StageEvent | LineEvent | CompleteEvent | ErrorEvent
