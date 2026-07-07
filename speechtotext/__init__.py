from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    # Single source of truth: the installed dist metadata, itself built from
    # pyproject.toml. Prevents this string from drifting out of sync.
    __version__ = _pkg_version("speechtotext")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"

del PackageNotFoundError, _pkg_version
