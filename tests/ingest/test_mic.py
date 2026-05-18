import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf

from speechtotext.ingest.mic import _install_stop_signals, record_to_file

_SKIP_SIGNALS = pytest.mark.skipif(
    sys.platform == "win32",
    reason="os.kill(SIGTERM/SIGINT) calls TerminateProcess on Windows, not the Python handler",
)


def test_record_writes_flac(tmp_path: Path):
    out = tmp_path / "rec.flac"
    fake_chunks = [
        np.zeros((1600, 1), dtype=np.int16),
        np.ones((1600, 1), dtype=np.int16),
    ]
    stop = MagicMock()
    stop.is_set.side_effect = [False, False, True]

    with (
        patch("sounddevice.InputStream") as stream_cls,
        patch("soundfile.SoundFile") as sf_cls,
    ):
        stream = stream_cls.return_value.__enter__.return_value
        stream.read.side_effect = [(c, False) for c in fake_chunks]
        sf_handle = sf_cls.return_value.__enter__.return_value

        record_to_file(out, sample_rate=16000, channels=1, stop_event=stop)

    assert sf_cls.call_args.args[0] == str(out)
    assert sf_handle.write.call_count == 2


@_SKIP_SIGNALS
def test_install_stop_signals_sets_event_on_sigterm():
    """Verify SIGTERM into the registered handler sets stop_event."""
    stop = threading.Event()
    with _install_stop_signals(stop):
        # Send ourselves SIGTERM; handler should flip the event.
        os.kill(os.getpid(), signal.SIGTERM)
        # signal handlers run synchronously on the main thread between bytecodes;
        # give the interpreter a tick to dispatch.
        time.sleep(0.05)
        assert stop.is_set(), "SIGTERM should have set the stop_event"


@_SKIP_SIGNALS
def test_install_stop_signals_sets_event_on_sigint():
    stop = threading.Event()
    with _install_stop_signals(stop):
        os.kill(os.getpid(), signal.SIGINT)
        time.sleep(0.05)
        assert stop.is_set(), "SIGINT should have set the stop_event"


@_SKIP_SIGNALS
def test_install_stop_signals_restores_handlers():
    """Prior handler should be restored after the context manager exits."""
    sentinel_called: list[bool] = []

    def _prior(_sig, _frame):
        sentinel_called.append(True)

    original = signal.signal(signal.SIGTERM, _prior)
    try:
        stop = threading.Event()
        with _install_stop_signals(stop):
            pass  # handler temporarily replaced
        # Restored — sending SIGTERM should call _prior, not flip stop.
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(0.05)
        assert sentinel_called == [True]
        assert not stop.is_set()
    finally:
        signal.signal(signal.SIGTERM, original)


@_SKIP_SIGNALS
def test_install_stop_signals_skips_in_worker_thread():
    """signal.signal raises ValueError off the main thread; we swallow it."""
    error: list[BaseException] = []

    def _runner() -> None:
        try:
            stop = threading.Event()
            with _install_stop_signals(stop):
                # should not raise; just no-op
                pass
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    t = threading.Thread(target=_runner)
    t.start()
    t.join()
    assert error == []


@_SKIP_SIGNALS
def test_record_to_file_survives_sigterm_with_valid_output(tmp_path: Path):
    """End-to-end: a child process recording to a file should produce a valid
    FLAC file even when killed with SIGTERM mid-loop. Uses mocked audio I/O
    inside the child to keep the test hermetic."""
    out = tmp_path / "rec.flac"
    script = tmp_path / "runner.py"
    script.write_text(
        f"""
import sys, os, time
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np

from speechtotext.ingest import mic

# Replace the sounddevice InputStream with a generator that emits silent blocks
# forever so the recorder is "live" when SIGTERM arrives. SoundFile stays real
# so the file on disk actually has a valid FLAC stream after __exit__.
fake_stream = MagicMock()
fake_stream.__enter__.return_value = fake_stream
fake_stream.__exit__.return_value = False
def _read(n):
    return np.zeros((n, 1), dtype=np.int16), False
fake_stream.read.side_effect = _read

with patch("sounddevice.InputStream", return_value=fake_stream):
    mic.record_to_file(Path({str(out)!r}), sample_rate=16000, channels=1, block_size=1600)
"""
    )
    proc = subprocess.Popen([sys.executable, str(script)])
    # let it record ~0.5s, then SIGTERM
    time.sleep(0.5)
    proc.terminate()  # SIGTERM
    proc.wait(timeout=5)
    assert proc.returncode == 0, "child should exit cleanly after SIGTERM"
    assert out.exists()
    # File must be a readable FLAC with correct properties.
    info = sf.info(str(out))
    assert info.samplerate == 16000
    assert info.channels == 1
    assert info.frames > 0, "should have captured at least one frame"
