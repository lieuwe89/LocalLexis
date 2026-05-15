from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from speechtotext.ingest.mic import record_to_wav


def test_record_writes_wav(tmp_path: Path):
    out = tmp_path / "rec.wav"
    fake_chunks = [
        np.zeros((1600, 1), dtype=np.int16),
        np.ones((1600, 1), dtype=np.int16),
    ]
    stop = MagicMock()
    stop.is_set.side_effect = [False, False, True]

    with (
        patch("speechtotext.ingest.mic.sd.InputStream") as stream_cls,
        patch("speechtotext.ingest.mic.sf.SoundFile") as sf_cls,
    ):
        stream = stream_cls.return_value.__enter__.return_value
        stream.read.side_effect = [(c, False) for c in fake_chunks]
        sf_handle = sf_cls.return_value.__enter__.return_value

        record_to_wav(out, sample_rate=16000, channels=1, stop_event=stop)

    assert sf_cls.call_args.args[0] == str(out)
    assert sf_handle.write.call_count == 2
