import json

from speechtotext.client import upload_queue
from speechtotext.client.paths import outbox_dir


class FakeHubClient:
    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.uploaded: list[str] = []

    def upload_audio(self, path):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("hub down")
        self.uploaded.append(path.name)
        return {"job_id": "hub-job-1", "bytes_received": path.stat().st_size}


def _make_audio(tmp_path, name="a.wav"):
    p = tmp_path / name
    p.write_bytes(b"RIFF" + b"\x00" * 50)
    return p


def test_enqueue_copies_into_outbox(tmp_path):
    audio = _make_audio(tmp_path)
    entry = upload_queue.enqueue(audio, job_id="local-1")
    assert entry.audio_path.parent == outbox_dir()
    assert entry.audio_path.exists()
    meta = json.loads(entry.meta_path.read_text())
    assert meta["job_id"] == "local-1"
    assert audio.exists()  # source untouched


def test_pending_lists_oldest_first(tmp_path):
    e1 = upload_queue.enqueue(_make_audio(tmp_path, "one.wav"), job_id="j1")
    e2 = upload_queue.enqueue(_make_audio(tmp_path, "two.wav"), job_id="j2")
    names = [e.audio_path.name for e in upload_queue.pending()]
    assert names.index(e1.audio_path.name) < names.index(e2.audio_path.name)


def test_sweep_uploads_and_removes(tmp_path):
    upload_queue.enqueue(_make_audio(tmp_path), job_id="j1")
    hub = FakeHubClient()
    done = upload_queue.sweep(hub)
    assert len(done) == 1
    assert done[0].job_id == "j1"
    assert upload_queue.pending() == []
    assert hub.uploaded  # actually hit the client


def test_sweep_keeps_entry_on_failure(tmp_path):
    upload_queue.enqueue(_make_audio(tmp_path), job_id="j1")
    hub = FakeHubClient(fail_times=1)
    done = upload_queue.sweep(hub)
    assert done == []
    assert len(upload_queue.pending()) == 1
    # next sweep succeeds
    assert len(upload_queue.sweep(hub)) == 1


def test_sweep_stops_batch_after_first_failure(tmp_path):
    upload_queue.enqueue(_make_audio(tmp_path, "one.wav"), job_id="j1")
    upload_queue.enqueue(_make_audio(tmp_path, "two.wav"), job_id="j2")
    hub = FakeHubClient(fail_times=1)
    upload_queue.sweep(hub)
    # first failed -> batch stopped, both still pending
    assert len(upload_queue.pending()) == 2
