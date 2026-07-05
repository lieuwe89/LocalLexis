from __future__ import annotations

import threading
from pathlib import Path

import httpx
import numpy as np
import pytest
import soundfile as sf

from speechtotext.asr.remote import RemoteWhisperASR, _split_on_silence
from speechtotext.pipeline import CancelledError

SR = 16000


def _tone(seconds: float, freq: float = 440.0, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SR), dtype=np.float32)


def _write_wav(path: Path, samples: np.ndarray) -> Path:
    sf.write(str(path), samples, SR, subtype="PCM_16")
    return path


class TestSplitOnSilence:
    def test_empty(self):
        assert _split_on_silence(np.array([], dtype=np.float32), SR) == []

    def test_splits_at_silence(self):
        samples = np.concatenate([_tone(2.0), _silence(1.0), _tone(2.0)])
        chunks = _split_on_silence(samples, SR)
        assert len(chunks) == 2
        # Cut point lands inside the silence (2.0s .. 3.0s).
        assert 2.0 < chunks[0][1] < 3.0
        assert chunks[0][1] == chunks[1][0]

    def test_chunks_tile_whole_file(self):
        samples = np.concatenate(
            [_tone(1.5), _silence(0.6), _tone(3.0), _silence(0.5), _tone(1.0)]
        )
        chunks = _split_on_silence(samples, SR)
        assert chunks[0][0] == 0.0
        assert chunks[-1][1] == pytest.approx(len(samples) / SR)
        for (_, a_end), (b_start, _) in zip(chunks, chunks[1:]):
            assert a_end == pytest.approx(b_start)

    def test_no_silence_hard_split_at_max(self):
        samples = _tone(130.0)
        chunks = _split_on_silence(samples, SR, max_chunk_seconds=60.0)
        assert len(chunks) == 3
        assert all(end - start <= 60.0 + 1e-6 for start, end in chunks)

    def test_short_silence_not_a_cut(self):
        # 0.1s gap is below the 0.4s minimum silence.
        samples = np.concatenate([_tone(1.0), _silence(0.1), _tone(1.0)])
        chunks = _split_on_silence(samples, SR)
        assert len(chunks) == 1


class _Recorder:
    def __init__(self, text: str = "hallo wereld", status: int = 200):
        self.requests: list[httpx.Request] = []
        self._text = text
        self._status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._status != 200:
            return httpx.Response(self._status, text="boom")
        return httpx.Response(200, json={"text": self._text})


def _make_asr(handler, **kwargs) -> RemoteWhisperASR:
    return RemoteWhisperASR(
        base_url="http://testserver/v1",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


class TestRemoteWhisperASR:
    def test_transcribes_chunks_with_timestamps(self, tmp_path: Path):
        wav = _write_wav(
            tmp_path / "a.wav",
            np.concatenate([_tone(2.0), _silence(1.0), _tone(2.0)]),
        )
        rec = _Recorder()
        segments = _make_asr(rec).transcribe(wav, language="nl")
        assert len(rec.requests) == 2
        assert len(segments) == 2
        assert all(s.text == "hallo wereld" for s in segments)
        assert segments[0].start == 0.0
        assert segments[0].end == segments[1].start
        assert segments[1].end == pytest.approx(5.0, abs=0.05)
        assert all(s.language == "nl" for s in segments)

    def test_request_carries_model_and_language(self, tmp_path: Path):
        wav = _write_wav(tmp_path / "a.wav", _tone(1.0))
        rec = _Recorder()
        _make_asr(rec, model="whisper-v3").transcribe(wav, language="nl")
        body = rec.requests[0].read()
        assert rec.requests[0].url.path == "/v1/audio/transcriptions"
        assert b'name="model"' in body and b"whisper-v3" in body
        assert b'name="language"' in body and b"nl" in body
        assert b'name="file"' in body

    def test_no_language_field_when_auto(self, tmp_path: Path):
        wav = _write_wav(tmp_path / "a.wav", _tone(1.0))
        rec = _Recorder()
        _make_asr(rec).transcribe(wav, language=None)
        assert b'name="language"' not in rec.requests[0].read()

    def test_empty_text_chunks_dropped(self, tmp_path: Path):
        wav = _write_wav(tmp_path / "a.wav", _tone(1.0))
        rec = _Recorder(text="   ")
        assert _make_asr(rec).transcribe(wav, language=None) == []

    def test_progress_reaches_one(self, tmp_path: Path):
        wav = _write_wav(
            tmp_path / "a.wav",
            np.concatenate([_tone(2.0), _silence(1.0), _tone(2.0)]),
        )
        seen: list[float] = []
        _make_asr(_Recorder()).transcribe(
            wav, language=None, on_progress=seen.append
        )
        assert len(seen) == 2
        assert seen == sorted(seen)
        assert seen[-1] == pytest.approx(1.0)

    def test_server_error_raises(self, tmp_path: Path):
        wav = _write_wav(tmp_path / "a.wav", _tone(1.0))
        with pytest.raises(RuntimeError, match="remote ASR error 500"):
            _make_asr(_Recorder(status=500)).transcribe(wav, language=None)

    def test_connection_error_raises_with_hint(self, tmp_path: Path):
        wav = _write_wav(tmp_path / "a.wav", _tone(1.0))

        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        asr = _make_asr(refuse)
        with pytest.raises(RuntimeError, match="Is the FastFlowLM/Lemonade server"):
            asr.transcribe(wav, language=None)

    def test_cancel_before_first_chunk(self, tmp_path: Path):
        wav = _write_wav(tmp_path / "a.wav", _tone(1.0))
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(CancelledError):
            _make_asr(_Recorder()).transcribe(
                wav, language=None, cancel_event=cancel
            )

    def test_label(self):
        asr = _make_asr(_Recorder(), model="whisper-v3")
        assert asr.label == "remote-whisper:whisper-v3"
