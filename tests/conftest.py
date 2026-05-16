# tests/conftest.py
"""Project-wide pytest configuration and fixtures.

This module is auto-discovered by pytest and applies to every test in the
``tests/`` tree. It provides two autouse fixtures that harden the suite
against state leakage between tests:

* :func:`_env_snapshot` — snapshots ``os.environ`` before each test and
  restores it afterwards. Defends against tests that mutate the process
  environment directly (i.e., not via :class:`pytest.MonkeyPatch`).
* :func:`_cwd_snapshot` — restores the current working directory after
  each test, in case a test (or a fixture it used) called ``os.chdir``.

Composability with ``monkeypatch``
----------------------------------
Both fixtures perform purely *restorative* operations and run in ``finally``
blocks. They compose safely with :class:`pytest.MonkeyPatch`: when both are
in effect, monkeypatch's teardown runs first (innermost), then these run
and see no further changes to undo (idempotent no-op). The reverse order
is also safe.

References
----------
* ``CONFY_DESIGN_SPECIFICATION.md`` §7 (Testing Strategy)
* Pytest fixtures docs: https://docs.pytest.org/en/stable/how-to/fixtures.html
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _env_snapshot() -> Iterator[None]:
    """Snapshot ``os.environ`` before the test; restore afterwards.

    The restoration handles all three mutation kinds:

    1. **Added** keys (present after, absent before) are deleted.
    2. **Modified** keys (different value) are reset to their original value.
    3. **Removed** keys (absent after, present before) are re-added.

    This is *additive* to :class:`pytest.MonkeyPatch`'s own snapshot/restore;
    running both is idempotent because we operate on a dict diff, not a log
    of operations.
    """
    original: dict[str, str] = dict(os.environ)
    try:
        yield
    finally:
        current_keys = list(os.environ.keys())
        # Remove keys that weren't present before
        for k in current_keys:
            if k not in original:
                del os.environ[k]
        # Restore modified/removed keys to their original values
        for k, v in original.items():
            if os.environ.get(k) != v:
                os.environ[k] = v


@pytest.fixture(autouse=True)
def _cwd_snapshot() -> Iterator[None]:
    """Restore the current working directory after each test.

    Some tests :code:`monkeypatch.chdir(tmp_path)` to make relative-path
    behavior (e.g., ``.env`` discovery in the CWD) deterministic.
    Monkeypatch normally restores CWD on teardown, but this fixture acts as
    a defense-in-depth against fixtures or helpers that ``os.chdir`` directly.
    """
    original = os.getcwd()
    try:
        yield
    finally:
        try:
            current = os.getcwd()
        except (FileNotFoundError, OSError):
            # CWD was deleted (e.g., tmp_path cleanup raced ahead). Restore
            # unconditionally.
            current = None
        if current != original:
            os.chdir(original)
