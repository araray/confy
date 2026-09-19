# confy/__init__.py
"""
confy – Minimal Python configuration library.

Import `Config` from `confy.loader` and `MissingMandatoryConfig` from `confy.exceptions`.

New in 0.4.0:
    - Multi-file config loading via ``file_paths`` parameter
    - App-namespaced defaults via ``app_defaults`` and ``app()`` accessor
    - Per-app env var routing via ``app_prefixes``
    - Optional provenance tracking via ``track_provenance``
    - Utility functions in ``confy.utils``

New (SF-2 v1):
    - Additive dot-path list indexing in ``get_by_dot``/``set_by_dot``
    - ``contains_dot(config, key)`` non-raising existence check
"""

from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _pkg_version

from .loader import contains_dot

try:
    # Single source of truth: the version recorded in package metadata
    # (i.e. [project].version in pyproject.toml at install/build time).
    __version__ = _pkg_version("confy")
except _PackageNotFoundError:  # pragma: no cover - running from a source tree
    # Fallback for environments where confy is importable but not installed
    # (e.g. sys.path manipulation). Keep in sync with pyproject.toml.
    __version__ = "0.4.2"

__all__ = ["contains_dot", "__version__"]
