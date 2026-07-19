import importlib

import pytest
import pytest_asyncio  # noqa: F401  # ensure plugin loads


@pytest.fixture(autouse=True)
def _isolated_app_data(tmp_path_factory, monkeypatch):
    """Redirect app-data lookups so tests don't trample the developer's
    real ~/Library/.../locallexis dir and tests can't leak state.

    Covers both the LibraryDB SQLite path and the workspace identity
    file used by speechtotext.api.workspace, plus load_config() so a real
    ~/.config/speechtotext/config.toml default_out_dir never becomes a
    test app's library/incoming dir.

    Implementation note: modules are resolved with importlib.import_module,
    which returns the sys.modules entry — the same object a call-time
    ``from a.b.c import f`` in application code resolves. A plain
    ``import a.b.c as x`` instead binds via parent-package ATTRIBUTE walk,
    which can point at a different module object after a test wipes and
    re-imports sys.modules entries (see test_sidecar_cold_start), making
    the patch land on a module nothing else uses.
    """
    _library_db = importlib.import_module("speechtotext.api.library_db")
    _secrets_store = importlib.import_module("speechtotext.api.secrets_store")
    _tls = importlib.import_module("speechtotext.api.tls")
    _workspace = importlib.import_module("speechtotext.api.workspace")
    _client_paths = importlib.import_module("speechtotext.client.paths")
    _app = importlib.import_module("speechtotext.api.app")
    _config = importlib.import_module("speechtotext.config")

    data_dir = tmp_path_factory.mktemp("appdata")
    monkeypatch.setattr(
        _library_db, "default_app_data_dir", lambda: data_dir
    )
    monkeypatch.setattr(
        _library_db, "default_db_path", lambda: data_dir / "library.db"
    )
    # workspace, secrets_store, and tls all import default_app_data_dir
    # at module load, so we patch each module-local binding too.
    monkeypatch.setattr(_workspace, "default_app_data_dir", lambda: data_dir)
    monkeypatch.setattr(
        _secrets_store, "default_app_data_dir", lambda: data_dir
    )
    monkeypatch.setattr(_tls, "default_app_data_dir", lambda: data_dir)
    # The client package resolves outbox_dir()/synced_dir() via its own
    # module-local default_app_data_dir binding; point it at the same temp
    # dir so joined-mode runtime tests never write to the real home.
    monkeypatch.setattr(_client_paths, "default_app_data_dir", lambda: data_dir)
    # create_app() reads the developer's real config file for
    # default_out_dir; a stray value there would register a REAL dir as a
    # library dir in every test app (and /trash purge tests would then
    # touch it). Serve defaults instead.
    monkeypatch.setattr(_app, "load_config", lambda *a, **k: _config.Config())


def pytest_collection_modifyitems(config, items):
    pass
