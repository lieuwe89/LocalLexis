import pytest
import pytest_asyncio  # noqa: F401  # ensure plugin loads


@pytest.fixture(autouse=True)
def _isolated_library_db(tmp_path_factory, monkeypatch):
    """Point every create_app() in api tests at a throw-away SQLite DB so
    the suite doesn't trample the developer's real ~/Library/.../library.db
    and tests can't leak state across each other."""
    db_dir = tmp_path_factory.mktemp("libdb")
    monkeypatch.setattr(
        "speechtotext.api.library_db.default_db_path",
        lambda: db_dir / "library.db",
    )


def pytest_collection_modifyitems(config, items):
    pass
