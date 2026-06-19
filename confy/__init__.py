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
"""

__version__ = "0.4.0"
