from __future__ import annotations

import threading
from pathlib import Path

import sounddevice as sd
import soundfile as sf


def record_to_wav(
    out_path: Path,
    sample_rate: int = 16000,
    channels: int = 1,
    block_size: int = 1600,
    stop_event: threading.Event | None = None,
    device: str | int | None = None,
) -> Path:
    stop = stop_event or threading.Event()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with sf.SoundFile(
        str(out_path),
        mode="w",
        samplerate=sample_rate,
        channels=channels,
        subtype="PCM_16",
    ) as fh, sd.InputStream(
        samplerate=sample_rate,
        channels=channels,
        dtype="int16",
        blocksize=block_size,
        device=device,
    ) as stream:
        while not stop.is_set():
            data, _overflow = stream.read(block_size)
            fh.write(data)

    return out_path
