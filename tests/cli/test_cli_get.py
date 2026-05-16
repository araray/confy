# tests/cli/test_cli_get.py
"""CLI ``get KEY`` subcommand tests.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §6 — CLI Specification
* ``confy/cli.py`` ``get()`` (lines 189-211)

What ``get`` does
-----------------
Prints the value at the given dot-notation key as **JSON** (so
``str → "..."``, ``int → 1``, etc.). Exit code is ``0`` on success,
``1`` on either missing key (yellow message) or invalid path (red
message).
"""

from __future__ import annotations

import json

import pytest

from confy.cli import cli

pytestmark = pytest.mark.cli


class TestGetHappyPath:
    """Successful retrieval of various value types."""

    def test_top_level_string(self, runner, json_config) -> None:
        fp = json_config({"k": "v"})
        result = runner.invoke(cli, ["-c", fp, "get", "k"])
        assert result.exit_code == 0
        # Output is JSON-encoded, so a string is double-quoted.
        assert json.loads(result.stdout) == "v"

    def test_top_level_int(self, runner, json_config) -> None:
        fp = json_config({"port": 5432})
        result = runner.invoke(cli, ["-c", fp, "get", "port"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == 5432

    def test_top_level_bool(self, runner, json_config) -> None:
        fp = json_config({"flag": True})
        result = runner.invoke(cli, ["-c", fp, "get", "flag"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) is True

    def test_top_level_null(self, runner, json_config) -> None:
        fp = json_config({"x": None})
        result = runner.invoke(cli, ["-c", fp, "get", "x"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) is None

    def test_top_level_list(self, runner, json_config) -> None:
        fp = json_config({"lst": [1, 2, 3]})
        result = runner.invoke(cli, ["-c", fp, "get", "lst"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == [1, 2, 3]

    def test_nested_value(self, runner, json_config) -> None:
        fp = json_config({"db": {"host": "h", "port": 5432}})
        result = runner.invoke(cli, ["-c", fp, "get", "db.host"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == "h"

    def test_deeply_nested_value(self, runner, json_config) -> None:
        fp = json_config({"a": {"b": {"c": {"d": "found"}}}})
        result = runner.invoke(cli, ["-c", fp, "get", "a.b.c.d"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == "found"

    def test_get_subtree_returns_object(self, runner, json_config) -> None:
        """Retrieving an intermediate key returns the whole subtree."""
        fp = json_config({"db": {"host": "h", "port": 5432}})
        result = runner.invoke(cli, ["-c", fp, "get", "db"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"host": "h", "port": 5432}


class TestGetErrors:
    """Error paths: missing keys, invalid paths."""

    def test_missing_top_level_key_exit_1(self, runner, json_config) -> None:
        fp = json_config({"k": "v"})
        result = runner.invoke(cli, ["-c", fp, "get", "missing"])
        assert result.exit_code == 1
        assert "not found" in result.stderr.lower()
        assert "missing" in result.stderr

    def test_missing_nested_key_exit_1(self, runner, json_config) -> None:
        fp = json_config({"db": {"host": "h"}})
        result = runner.invoke(cli, ["-c", fp, "get", "db.password"])
        assert result.exit_code == 1
        assert "password" in result.stderr

    def test_traverse_through_scalar_treated_as_missing(
        self, runner, json_config
    ) -> None:
        """Asking for ``a.b`` when ``a`` is an int yields a "not found"
        result (the CLI's ``get`` swallows the underlying TypeError into
        a missing-key message — see lines 199 and 205-208 in cli.py).
        """
        fp = json_config({"a": 42})
        result = runner.invoke(cli, ["-c", fp, "get", "a.b"])
        assert result.exit_code == 1
        assert "a.b" in result.stderr


class TestGetWithOverrides:
    """Values supplied by ``--overrides`` are accessible via ``get``."""

    def test_get_after_override(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(
            cli,
            ["-c", fp, "--overrides", 'added:"new"', "get", "added"],
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout) == "new"

    def test_get_overridden_value(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(cli, ["-c", fp, "--overrides", "a:99", "get", "a"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == 99
