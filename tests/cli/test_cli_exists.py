# tests/cli/test_cli_exists.py
"""CLI ``exists KEY`` subcommand tests.

Specification reference
-----------------------
* ``confy/cli.py`` ``exists()`` (lines 289-300)

What ``exists`` does
--------------------
Exit code 0 if the key is in the final config, 1 otherwise. Also prints
``"true"`` or ``"false"`` to stdout for scripting convenience.
"""

from __future__ import annotations

import pytest

from confy.cli import cli

pytestmark = pytest.mark.cli


class TestExists:
    def test_existing_top_level(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(cli, ["-c", fp, "exists", "a"])
        assert result.exit_code == 0
        assert result.stdout.strip() == "true"

    def test_missing_top_level(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(cli, ["-c", fp, "exists", "missing"])
        assert result.exit_code == 1
        # Even on exit 1 we print "false" so scripts can branch on output
        # if they choose to:
        assert result.stdout.strip() == "false"

    def test_nested_present(self, runner, json_config) -> None:
        fp = json_config({"db": {"host": "h"}})
        result = runner.invoke(cli, ["-c", fp, "exists", "db.host"])
        assert result.exit_code == 0

    def test_nested_missing(self, runner, json_config) -> None:
        fp = json_config({"db": {"host": "h"}})
        result = runner.invoke(cli, ["-c", fp, "exists", "db.port"])
        assert result.exit_code == 1

    def test_value_of_none_still_exists(self, runner, json_config) -> None:
        """A key with explicit ``null`` value is still present."""
        fp = json_config({"k": None})
        result = runner.invoke(cli, ["-c", fp, "exists", "k"])
        assert result.exit_code == 0

    def test_traverse_through_scalar_is_false(self, runner, json_config) -> None:
        """``a.b`` when ``a`` is a scalar → not present."""
        fp = json_config({"a": 42})
        result = runner.invoke(cli, ["-c", fp, "exists", "a.b"])
        assert result.exit_code == 1

    def test_exists_with_overrides_added_key(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(
            cli, ["-c", fp, "--overrides", "added:1", "exists", "added"]
        )
        assert result.exit_code == 0
