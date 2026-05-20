import pytest
import pytest_asyncio  # noqa: F401  # ensure plugin loads


@pytest.fixture(autouse=True)
def _isolated_app_data(tmp_path_factory, monkeypatch):
    """Redirect app-data lookups so tests don't trample the developer's
    real ~/Library/.../locallexis dir and tests can't leak state.

    Covers both the LibraryDB SQLite path and the workspace identity
    file used by speechtotext.api.workspace.

    Implementation note: monkeypatch.setattr by string path is brittle
    across tests that wipe sys.modules (e.g. test_sidecar_cold_start),
    because Python's import system does not re-bind a child attribute on
    a parent package when the child is already in sys.modules. Resolving
    the module via ``import ... as`` and monkeypatching the live object
    directly side-steps the broken parent attribute walk.
    """
    import speechtotext.api.library_db as _library_db
    import speechtotext.api.secrets_store as _secrets_store
    import speechtotext.api.workspace as _workspace

    data_dir = tmp_path_factory.mktemp("appdata")
    monkeypatch.setattr(
        _library_db, "default_app_data_dir", lambda: data_dir
    )
    monkeypatch.setattr(
        _library_db, "default_db_path", lambda: data_dir / "library.db"
    )
    # workspace.py and secrets_store.py import default_app_data_dir at
    # module load, so we patch the module-local bindings too.
    monkeypatch.setattr(_workspace, "default_app_data_dir", lambda: data_dir)
    monkeypatch.setattr(
        _secrets_store, "default_app_data_dir", lambda: data_dir
    )


def pytest_collection_modifyitems(config, items):
    pass
