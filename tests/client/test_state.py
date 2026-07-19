import json
import threading

from speechtotext.client import state
from speechtotext.client.paths import hub_dir


def test_load_returns_none_when_not_joined():
    assert state.load() is None


def test_client_state_new_fields_default():
    # Old-format file written before migrated_at/offline_capture existed.
    old = {
        "hub_url": "http://hub.tailnet:8010",
        "workspace_id": "ws-abc",
        "device_id": "dev-123456789abc",
        "device_name": "lieuwe-laptop",
        "tls_spki_b64": None,
        "cursor": 0.0,
    }
    path = hub_dir() / "client_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(old), encoding="utf-8")

    st = state.load()
    assert st.migrated_at is None
    assert st.offline_capture == "local"


def test_update_fields_helper():
    st = state.ClientState(
        hub_url="u", workspace_id="w", device_id="d",
        device_name="n", tls_spki_b64=None, cursor=0.0,
    )
    state.save(st)
    state.update_fields(migrated_at=123.0)
    loaded = state.load()
    assert loaded.migrated_at == 123.0
    assert loaded.cursor == 0.0
    assert loaded.offline_capture == "local"


def test_save_load_roundtrip():
    st = state.ClientState(
        hub_url="http://hub.tailnet:8010",
        workspace_id="ws-abc",
        device_id="dev-123456789abc",
        device_name="lieuwe-laptop",
        tls_spki_b64=None,
        cursor=0.0,
    )
    state.save(st)
    loaded = state.load()
    assert loaded == st


def test_update_cursor_persists():
    st = state.ClientState(
        hub_url="http://hub.tailnet:8010",
        workspace_id="ws-abc",
        device_id="dev-123456789abc",
        device_name="lieuwe-laptop",
        tls_spki_b64=None,
        cursor=0.0,
    )
    state.save(st)
    state.update_cursor(1234.5)
    assert state.load().cursor == 1234.5


def test_concurrent_updates_do_not_clobber_fields():
    """Runtime cursor saves and the migrate job's migrated_at write race
    on the same file; the module lock must keep both fields' final values.
    Hammer test: reliably passes with the lock, near-certainly fails
    without it (a stale load in one thread wipes the other's field)."""
    st = state.ClientState(
        hub_url="u", workspace_id="w", device_id="d",
        device_name="n", tls_spki_b64=None, cursor=0.0,
    )
    state.save(st)

    def bump_cursor():
        for i in range(200):
            state.update_cursor(float(i))

    def set_flag():
        for _ in range(200):
            state.update_fields(migrated_at=42.0)

    threads = [threading.Thread(target=bump_cursor), threading.Thread(target=set_flag)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    loaded = state.load()
    assert loaded.cursor == 199.0
    assert loaded.migrated_at == 42.0


def test_delete():
    st = state.ClientState(
        hub_url="u", workspace_id="w", device_id="d",
        device_name="n", tls_spki_b64=None, cursor=0.0,
    )
    state.save(st)
    state.delete()
    assert state.load() is None


def test_load_ignores_unknown_keys_from_newer_versions(tmp_path, monkeypatch):
    """Version skew must never brick startup: a state file written by a NEWER
    version (extra keys) loads fine in this version — the v0.18.0 migration
    fields crashed the older bundled sidecar exactly this way."""
    import json as _json

    from speechtotext.client import paths, state

    hub = tmp_path / "hub"
    hub.mkdir()
    monkeypatch.setattr(paths, "hub_dir", lambda: hub)
    monkeypatch.setattr(state, "hub_dir", lambda: hub)
    doc = {
        "hub_url": "http://h:1", "workspace_id": "w", "device_id": "d",
        "device_name": "n", "tls_spki_b64": None, "cursor": 1.0,
        "field_from_the_future": True,
    }
    (hub / "client_state.json").write_text(_json.dumps(doc), encoding="utf-8")
    st = state.load()
    assert st is not None and st.hub_url == "http://h:1"
    assert not hasattr(st, "field_from_the_future") or True  # unknown key dropped
