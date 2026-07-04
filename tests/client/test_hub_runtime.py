import time

from speechtotext.client import hub_runtime, identity, state


def _join_locally():
    identity.generate()
    st = state.ClientState(
        hub_url="http://hub:8010", workspace_id="ws", device_id="dev-1",
        device_name="laptop", tls_spki_b64=None, cursor=100.0,
    )
    state.save(st)
    return st


class FakeHubClient:
    def __init__(self):
        self.uploads = []

    def upload_audio(self, path):
        self.uploads.append(path.name)
        return {"job_id": "h1", "bytes_received": 1}

    def get_json(self, path):
        return {"workspace_id": "ws", "cursor": 100.0, "transcripts": []}

    def close(self):
        pass


def test_runtime_not_joined_reports_status():
    rt = hub_runtime.HubRuntime()
    assert rt.status()["joined"] is False


def test_runtime_joined_status_includes_hub_url():
    _join_locally()
    rt = hub_runtime.HubRuntime()
    s = rt.status()
    assert s["joined"] is True
    assert s["hub_url"] == "http://hub:8010"
    assert s["pending_uploads"] == 0


def test_enqueue_and_sweep_via_poke(tmp_path):
    _join_locally()
    audio = tmp_path / "rec.wav"
    audio.write_bytes(b"RIFF00")
    fake = FakeHubClient()
    sent = []
    rt = hub_runtime.HubRuntime(
        hub_client_factory=lambda st, ident: fake,
        on_entry_sent=lambda entry: sent.append(entry.job_id),
        period_s=3600.0,  # only poke triggers work in this test
    )
    rt.start()
    try:
        rt.enqueue_upload(audio, job_id="local-7")
        rt.poke()
        deadline = time.time() + 5.0
        while time.time() < deadline and not sent:
            time.sleep(0.02)
        assert sent == ["local-7"]
        assert len(fake.uploads) == 1  # the outbox copy was uploaded
        assert rt.status()["pending_uploads"] == 0
    finally:
        rt.stop()


def test_stop_terminates_thread_quickly():
    _join_locally()
    rt = hub_runtime.HubRuntime(
        hub_client_factory=lambda st, ident: FakeHubClient(),
        period_s=3600.0,
    )
    rt.start()
    t0 = time.time()
    rt.stop()
    assert time.time() - t0 < 2.0
