# tests/unit/test_version.py
"""``confy.__version__`` is single-sourced from package metadata.

Guards against the version drifting between ``pyproject.toml`` and a
hardcoded ``__init__.py`` string (which is exactly what happened between
0.4.0 and 0.4.2).
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

import pytest

import confy

pytestmark = pytest.mark.unit


def test_version_matches_installed_metadata() -> None:
    try:
        installed = version("confy")
    except PackageNotFoundError:  # pragma: no cover - source-tree runs only
        pytest.skip("confy is not installed; metadata unavailable")
    assert confy.__version__ == installed


def test_version_is_nonempty_string() -> None:
    assert isinstance(confy.__version__, str)
    assert confy.__version__
