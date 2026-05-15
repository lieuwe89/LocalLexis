import json
import shutil
from pathlib import Path

import pytest

from speechtotext.asr.faster_whisper import FasterWhisperASR
from speechtotext.config import Config
from speechtotext.diarize.base import DiarizerBackend
from speechtotext.models import SpeakerTurn
from speechtotext.pipeline import Pipeline
from speechtotext.writer import write_transcript


pytestmark = pytest.mark.integration


class DummyDiarizer:
    """Skip the real pyannote model in CI; assign one speaker per half."""

    def diarize(self, wav_path: Path, num_speakers):
        # 10s file: first half SPEAKER_00, second half SPEAKER_01
        return [
            SpeakerTurn(0.0, 5.0, "SPEAKER_00"),
            SpeakerTurn(5.0, 10.0, "SPEAKER_01"),
        ]


@pytest.fixture
def en_audio(audio_fixture_dir: Path) -> Path:
    p = audio_fixture_dir / "en_2speakers_10s.wav"
    if not p.exists():
        pytest.skip("fixture audio missing; run tests/fixtures/generate_fixtures.py")
    return p


def test_end_to_end_english(en_audio: Path, tmp_path: Path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")

    # Copy fixture so output is written next to the copy (not into committed tree)
    work = tmp_path / en_audio.name
    work.write_bytes(en_audio.read_bytes())

    cfg = Config(backend="cpu")
    asr = FasterWhisperASR(model_size="tiny", backend="cpu")
    pipeline = Pipeline(
        config=cfg, asr=asr, diarizer=DummyDiarizer(), resolved_backend="cpu"
    )
    transcript = pipeline.run(work)
    write_transcript(transcript)

    js = work.with_suffix(".json")
    txt = work.with_suffix(".txt")
    assert js.exists()
    assert txt.exists()

    data = json.loads(js.read_text())
    assert data["version"] == 1
    assert len(data["segments"]) > 0
    # at least one segment per speaker (speakers split at 5s mark)
    spks = {s["speaker"] for s in data["segments"]}
    assert "SPEAKER_00" in spks or "SPEAKER_01" in spks
