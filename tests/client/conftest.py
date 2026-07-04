import pytest


@pytest.fixture(autouse=True)
def _isolated_client_data(tmp_path_factory, monkeypatch):
    """Point the client package's app-data lookups at a temp dir so tests
    never touch the developer's real ~/Library/.../locallexis/hub."""
    import speechtotext.client.paths as _paths

    data_dir = tmp_path_factory.mktemp("clientdata")
    monkeypatch.setattr(_paths, "default_app_data_dir", lambda: data_dir)
