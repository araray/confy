# tests/unit/test_public_api_surface.py
"""Public-API surface snapshot for the ``confy`` package.

confy is a widely reused library: renaming, removing, or accidentally
adding a public name is an API break for downstream consumers (wairu,
llmcore, semantiscan, grimoire, ...). These tests pin the exact set of
public (non-underscore) names exposed by ``confy`` and ``confy.loader``
so any unintentional change fails CI loudly.

If a change here is INTENTIONAL, update the recorded lists below in the
same commit that changes the API, and mention it in the release notes.

Implementation note: each module is inspected in a fresh subprocess so
the snapshot cannot be polluted by import side effects of other tests
(e.g. an earlier ``import confy.cli`` binds a ``cli`` attribute onto the
``confy`` package in-process).
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

# --- Recorded public API surfaces (sorted) ---------------------------------

CONFY_PUBLIC_API = [
    "contains_dot",
    "exceptions",  # submodule, bound as a side effect of importing confy.loader
    "loader",  # submodule
    "provenance",  # submodule, bound as a side effect of importing confy.loader
]

CONFY_LOADER_PUBLIC_API = [
    # NOTE: this is the *importable surface*, which includes re-exported
    # stdlib/third-party names. That is deliberate: downstream code doing
    # ``from confy.loader import X`` breaks if any of these disappear.
    "Any",
    "Config",
    "Mapping",
    "MissingMandatoryConfig",
    "MutableSequence",
    "Path",
    "ProvenanceEntry",
    "ProvenanceStore",
    "Sequence",
    "Union",
    "contains_dot",
    "copy",
    "deep_merge",
    "find_dotenv",
    "get_by_dot",
    "json",
    "load_dotenv",
    "log",
    "logging",
    "os",
    "set_by_dot",
    "tomli",
]


def _public_names(module_name: str) -> list[str]:
    """Import ``module_name`` in a fresh interpreter and return its sorted
    public (non-underscore) attribute names."""
    code = (
        "import importlib, json; "
        f"m = importlib.import_module({module_name!r}); "
        "print(json.dumps(sorted(n for n in dir(m) if not n.startswith('_'))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_confy_package_public_surface_matches_snapshot() -> None:
    assert _public_names("confy") == CONFY_PUBLIC_API


def test_confy_loader_public_surface_matches_snapshot() -> None:
    assert _public_names("confy.loader") == CONFY_LOADER_PUBLIC_API


def test_confy_dunder_version_present() -> None:
    """__version__ is underscore-prefixed (excluded from the snapshot above)
    but is part of the public contract nonetheless."""
    import confy

    assert isinstance(confy.__version__, str)
    assert confy.__version__


def test_core_names_remain_importable() -> None:
    """Smoke check that the canonical import paths keep working."""
    from confy import contains_dot  # noqa: F401
    from confy.exceptions import MissingMandatoryConfig  # noqa: F401
    from confy.loader import (  # noqa: F401
        Config,
        deep_merge,
        get_by_dot,
        set_by_dot,
    )
