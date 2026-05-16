# tests/cli/conftest.py
"""Shared fixtures for CLI integration tests.

Provides:
    - :func:`runner`         — a :class:`click.testing.CliRunner`.
    - :func:`json_config`    — factory: writes a JSON file in tmp_path and
      returns its path string.
    - :func:`toml_config`    — factory: writes a TOML file in tmp_path and
      returns its path string.
    - :func:`defaults_file`  — factory: writes a JSON defaults file and
      returns its path.

Design choices
--------------
* We use **Click's** :class:`CliRunner` rather than :mod:`subprocess` to
  exercise the CLI: it's faster, deterministic, and gives clean
  ``stdout``/``stderr`` separation in Click ≥ 8.3.
* Each factory writes to ``tmp_path`` so files are cleaned up between
  tests; the autouse ``_env_snapshot`` / ``_cwd_snapshot`` fixtures from
  the project-wide ``conftest.py`` handle env + CWD hygiene.
* Tests assert on ``result.stdout`` and ``result.stderr`` separately
  (Click 8.3+ no longer merges them by default).
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    """A fresh CliRunner per test."""
    return CliRunner()


@pytest.fixture
def json_config(tmp_path) -> Callable[[dict], str]:
    """Factory: write a JSON config file to ``tmp_path`` and return path str.

    Usage::

        def test_x(json_config, runner):
            fp = json_config({"a": 1, "b": {"c": 2}})
            result = runner.invoke(cli, ['-c', fp, 'get', 'a'])
    """
    counter = {"n": 0}

    def _make(content: dict, name: str | None = None) -> str:
        counter["n"] += 1
        fname = name or f"config_{counter['n']}.json"
        path = tmp_path / fname
        path.write_text(json.dumps(content))
        return str(path)

    return _make


@pytest.fixture
def toml_config(tmp_path) -> Callable[[str], str]:
    """Factory: write a TOML config file (raw string) and return path str.

    Takes a raw TOML string rather than a dict, because rendering Python
    dicts to TOML losslessly is non-trivial and tests should be explicit
    about the TOML structure under test. For dict→TOML round-trip tests
    in the integration layer we use :mod:`tomli_w`; here we want to be
    able to write malformed or edge-shaped TOML directly.

    Usage::

        def test_x(toml_config, runner):
            fp = toml_config('[db]\\nhost = "h"\\n')
            result = runner.invoke(cli, ['-c', fp, 'get', 'db.host'])
    """
    counter = {"n": 0}

    def _make(content: str, name: str | None = None) -> str:
        counter["n"] += 1
        fname = name or f"config_{counter['n']}.toml"
        path = tmp_path / fname
        path.write_text(content)
        return str(path)

    return _make


@pytest.fixture
def defaults_file(tmp_path) -> Callable[[dict], str]:
    """Factory: write a JSON defaults file (for ``--defaults`` CLI arg)."""

    def _make(content: dict) -> str:
        path = tmp_path / "defaults.json"
        path.write_text(json.dumps(content))
        return str(path)

    return _make
