from __future__ import annotations

import signal
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def _install_stop_signals(stop: threading.Event) -> Iterator[None]:
    """Install SIGINT + SIGTERM handlers that set ``stop``.

    Ensures the recording loop exits cleanly so ``SoundFile.__exit__`` can
    finalise the file. Without this, SIGTERM bypasses the context managers and
    may leave the output file in an incomplete state.

    Signal handlers can only be installed in the main thread; if called from
    a worker thread we silently skip and rely on the caller's stop_event.
    """
    prev_handlers: dict[int, signal.Handlers | None] = {}

    def _set_stop(_sig: int, _frame) -> None:
        stop.set()

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                prev_handlers[sig] = signal.signal(sig, _set_stop)
            except ValueError:
                # not main thread; skip
                prev_handlers = {}
                break
        yield
    finally:
        for sig, prev in prev_handlers.items():
            try:
                signal.signal(sig, prev)
            except (ValueError, TypeError):
                pass


def record_to_file(
    out_path: Path,
    sample_rate: int = 16000,
    channels: int = 1,
    block_size: int = 1600,
    stop_event: threading.Event | None = None,
    device: str | int | None = None,
) -> Path:
    import sounddevice as sd  # lazy: deferred from module load to first record call
    import soundfile as sf  # lazy: deferred from module load to first record call

    stop = stop_event or threading.Event()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with _install_stop_signals(stop), sf.SoundFile(
        str(out_path),
        mode="w",
        samplerate=sample_rate,
        channels=channels,
        format="FLAC",
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
