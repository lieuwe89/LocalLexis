from speechtotext.client import state


def test_load_returns_none_when_not_joined():
    assert state.load() is None


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


def test_delete():
    st = state.ClientState(
        hub_url="u", workspace_id="w", device_id="d",
        device_name="n", tls_spki_b64=None, cursor=0.0,
    )
    state.save(st)
    state.delete()
    assert state.load() is None
