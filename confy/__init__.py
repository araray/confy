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

from .loader import contains_dot

__version__ = "0.4.0"

__all__ = ["contains_dot", "__version__"]
