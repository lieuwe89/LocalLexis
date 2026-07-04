import json

from speechtotext.client import state, sync_puller
from speechtotext.client.paths import synced_dir


def _joined_state(cursor=0.0):
    st = state.ClientState(
        hub_url="http://hub:8010", workspace_id="ws", device_id="dev-1",
        device_name="laptop", tls_spki_b64=None, cursor=cursor,
    )
    state.save(st)
    return st


class FakeHub:
    def __init__(self, pages):
        self.pages = pages  # list of responses to return in order
        self.calls: list[str] = []

    def get_json(self, path):
        self.calls.append(path)
        return self.pages.pop(0)


def _doc(tid, mtime, text="hello"):
    return {
        "id": tid,
        "segments": [{"speaker": "SPEAKER_00", "text": text}],
        "_mtime": mtime,
    }


def test_pull_once_writes_docs_and_advances_cursor():
    _joined_state(cursor=100.0)
    hub = FakeHub([{
        "workspace_id": "ws", "cursor": 200.0,
        "transcripts": [_doc("t1", 150.0), _doc("t2", 200.0)],
    }])
    written = sync_puller.pull_once(hub)
    assert sorted(p.name for p in written) == ["t1.json", "t2.json"]
    assert hub.calls == ["/sync/since/100.0"]
    assert state.load().cursor == 200.0
    saved = json.loads((synced_dir() / "t1.json").read_text())
    assert "id" not in saved
    assert saved["segments"][0]["text"] == "hello"


def test_pull_once_uses_snapshot_on_first_sync():
    _joined_state(cursor=0.0)
    hub = FakeHub([{
        "workspace_id": "ws", "cursor": 50.0,
        "transcripts": [_doc("t1", 50.0)],
    }])
    sync_puller.pull_once(hub)
    assert hub.calls[0].startswith("/sync/snapshot")


def test_pull_once_empty_delta_still_advances_cursor():
    _joined_state(cursor=100.0)
    hub = FakeHub([{
        "workspace_id": "ws", "cursor": 300.0, "transcripts": [],
    }])
    written = sync_puller.pull_once(hub)
    assert written == []
    assert state.load().cursor == 300.0


def test_pull_once_not_joined_is_noop():
    hub = FakeHub([])
    assert sync_puller.pull_once(hub) == []
    assert hub.calls == []
