# tests/cli/test_cli_dump.py
"""CLI ``dump`` subcommand tests.

Specification reference
-----------------------
* ``confy/cli.py`` ``dump()`` (lines 355-360)

What ``dump`` does
------------------
Prints the entire final (merged) config as indented JSON on stdout.
"""

from __future__ import annotations

import json

import pytest

from confy.cli import cli

pytestmark = pytest.mark.cli


class TestDump:
    def test_dump_simple(self, runner, json_config) -> None:
        fp = json_config({"a": 1, "b": "x"})
        result = runner.invoke(cli, ["-c", fp, "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"a": 1, "b": "x"}

    def test_dump_nested(self, runner, json_config) -> None:
        content = {"db": {"host": "h", "port": 5432}, "logging": {"level": "INFO"}}
        fp = json_config(content)
        result = runner.invoke(cli, ["-c", fp, "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == content

    def test_dump_with_overrides_shows_merged(self, runner, json_config) -> None:
        fp = json_config({"a": 1, "b": 2})
        result = runner.invoke(cli, ["-c", fp, "--overrides", "a:99,c:3", "dump"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed == {"a": 99, "b": 2, "c": 3}

    def test_dump_with_defaults(self, runner, json_config, defaults_file) -> None:
        df = defaults_file({"def_only": 1, "shared": "default"})
        fp = json_config({"shared": "file", "file_only": 2})
        result = runner.invoke(cli, ["--defaults", df, "-c", fp, "dump"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        # All three keys present, merged correctly:
        assert parsed == {
            "def_only": 1,
            "shared": "file",  # file wins
            "file_only": 2,
        }

    def test_dump_no_config_file(self, runner, defaults_file) -> None:
        """Dump works fine with no -c, falling back to other sources."""
        df = defaults_file({"only_def": "x"})
        result = runner.invoke(cli, ["--defaults", df, "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"only_def": "x"}

    def test_dump_empty_config(self, runner, json_config) -> None:
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {}

    def test_dump_pretty_printed(self, runner, json_config) -> None:
        """Output is indented for human readability."""
        fp = json_config({"a": 1, "b": {"c": 2}})
        result = runner.invoke(cli, ["-c", fp, "dump"])
        assert result.exit_code == 0
        assert "\n" in result.stdout  # indented = has newlines
        # And indented with 2 spaces:
        assert "  " in result.stdout
