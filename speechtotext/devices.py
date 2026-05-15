from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import sounddevice as sd

Hint = Literal["mic", "loopback", "mic+loopback", "unknown"]

_LOOPBACK_TOKENS = (
    "blackhole",
    "loopback",
    "voicemeeter",
    "soundflower",
    ".monitor",
    "monitor of",
    "stereo mix",
)
_MIC_TOKENS = (
    "microphone",
    "mic",
    "input",
    "line in",
    "airpods",
    "headset",
)


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    channels: int
    sample_rate: float
    default: bool
    hint: Hint


def classify(name: str) -> Hint:
    n = name.lower()
    is_loopback = any(tok in n for tok in _LOOPBACK_TOKENS)
    is_aggregate = "aggregate" in n
    is_mic = bool(re.search(r"\b(mic|microphone|input|line in|airpods|headset)\b", n))
    if is_aggregate and (is_loopback or is_mic):
        return "mic+loopback"
    if is_loopback:
        return "loopback"
    if is_mic:
        return "mic"
    return "unknown"


def _default_input_index() -> int | None:
    dev = sd.default.device
    if isinstance(dev, (tuple, list)):
        return dev[0] if dev else None
    return dev


def list_inputs(include_all: bool = False) -> list[AudioDevice]:
    raw = sd.query_devices()
    default_idx = _default_input_index()
    out: list[AudioDevice] = []
    for i, d in enumerate(raw):
        channels = int(d.get("max_input_channels", 0))
        if channels == 0 and not include_all:
            continue
        out.append(
            AudioDevice(
                index=i,
                name=str(d["name"]),
                channels=channels,
                sample_rate=float(d.get("default_samplerate", 0.0)),
                default=(i == default_idx),
                hint=classify(str(d["name"])),
            )
        )
    return out
