import tomllib
from pathlib import Path

import speechtotext

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_package_importable():
    assert hasattr(speechtotext, "__version__")
    assert isinstance(speechtotext.__version__, str)


def test_version_matches_pyproject():
    # __version__ is sourced from installed dist metadata; it must not drift
    # from the single source of truth in pyproject.toml. If this fails after a
    # version bump, reinstall the package (e.g. `pip install -e .`).
    declared = tomllib.loads(_PYPROJECT.read_text())["project"]["version"]
    assert speechtotext.__version__ == declared
