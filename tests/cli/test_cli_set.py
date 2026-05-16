# tests/cli/test_cli_set.py
"""CLI ``set KEY VALUE`` subcommand tests.

Specification reference
-----------------------
* ``confy/cli.py`` ``set()`` (lines 214-286)

What ``set`` does
-----------------
Writes a new value to the *source* config file (NOT the merged final
config). The file format (JSON / TOML) is preserved. Requires the
``-c`` / ``--config`` option to be set. Values are JSON-parsed; if
parsing fails, the value is treated as a raw string.

Important: this command **mutates the file on disk**. Tests use
``tmp_path`` so each run starts from a clean state.
"""

from __future__ import annotations

import json

import pytest
import tomli

from confy.cli import cli

pytestmark = pytest.mark.cli


# =============================================================================
# Successful sets (JSON)
# =============================================================================


class TestSetJson:
    def test_set_top_level_new_key(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(cli, ["-c", fp, "set", "b", "42"])
        assert result.exit_code == 0
        with open(fp) as f:
            data = json.load(f)
        assert data == {"a": 1, "b": 42}

    def test_set_top_level_overwrite(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(cli, ["-c", fp, "set", "a", "99"])
        assert result.exit_code == 0
        with open(fp) as f:
            data = json.load(f)
        assert data == {"a": 99}

    def test_set_nested_creates_path(self, runner, json_config) -> None:
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "set", "db.host", '"h"'])
        assert result.exit_code == 0
        with open(fp) as f:
            data = json.load(f)
        assert data == {"db": {"host": "h"}}

    def test_set_deeply_nested(self, runner, json_config) -> None:
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "set", "a.b.c.d", '"deep"'])
        assert result.exit_code == 0
        with open(fp) as f:
            data = json.load(f)
        assert data == {"a": {"b": {"c": {"d": "deep"}}}}

    def test_set_existing_nested(self, runner, json_config) -> None:
        fp = json_config({"db": {"host": "h", "port": 5432}})
        result = runner.invoke(cli, ["-c", fp, "set", "db.port", "9999"])
        assert result.exit_code == 0
        with open(fp) as f:
            data = json.load(f)
        assert data == {"db": {"host": "h", "port": 9999}}

    def test_set_json_value_types(self, runner, json_config) -> None:
        fp = json_config({})
        runner.invoke(cli, ["-c", fp, "set", "i", "42"])
        runner.invoke(cli, ["-c", fp, "set", "s", '"text"'])
        runner.invoke(cli, ["-c", fp, "set", "b", "true"])
        runner.invoke(cli, ["-c", fp, "set", "n", "null"])
        runner.invoke(cli, ["-c", fp, "set", "lst", "[1, 2, 3]"])
        runner.invoke(cli, ["-c", fp, "set", "obj", '{"x": 1}'])
        with open(fp) as f:
            data = json.load(f)
        assert data["i"] == 42
        assert data["s"] == "text"
        assert data["b"] is True
        assert data["n"] is None
        assert data["lst"] == [1, 2, 3]
        assert data["obj"] == {"x": 1}

    def test_set_raw_string_when_not_valid_json(self, runner, json_config) -> None:
        """If the value isn't JSON-parseable, it's stored as a string."""
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "set", "k", "raw_value"])
        assert result.exit_code == 0
        with open(fp) as f:
            data = json.load(f)
        # Stored as a string, not as some other type:
        assert data["k"] == "raw_value"

    def test_set_prints_confirmation(self, runner, json_config) -> None:
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "set", "k", "1"])
        # Confirmation includes key, value, and file path:
        assert "k" in result.stdout
        assert "1" in result.stdout
        assert fp in result.stdout


# =============================================================================
# Successful sets (TOML)
# =============================================================================


class TestSetToml:
    """When the source file is TOML, ``set`` writes back as TOML."""

    def test_set_in_toml_file(self, runner, toml_config) -> None:
        fp = toml_config('[db]\nhost = "h"\n')
        result = runner.invoke(cli, ["-c", fp, "set", "db.port", "5432"])
        assert result.exit_code == 0
        with open(fp, "rb") as f:
            data = tomli.load(f)
        assert data["db"]["port"] == 5432
        assert data["db"]["host"] == "h"

    def test_set_new_section_in_toml(self, runner, toml_config) -> None:
        fp = toml_config("a = 1\n")
        result = runner.invoke(cli, ["-c", fp, "set", "section.key", '"value"'])
        assert result.exit_code == 0
        with open(fp, "rb") as f:
            data = tomli.load(f)
        assert data["section"]["key"] == "value"
        assert data["a"] == 1

    def test_set_toml_preserves_format(self, runner, toml_config) -> None:
        """After ``set``, the file should still parse as valid TOML."""
        fp = toml_config('a = 1\n[db]\nhost = "h"\n')
        result = runner.invoke(cli, ["-c", fp, "set", "b", "2"])
        assert result.exit_code == 0
        # File still parses cleanly:
        with open(fp, "rb") as f:
            data = tomli.load(f)
        assert data["a"] == 1
        assert data["b"] == 2
        assert data["db"]["host"] == "h"


# =============================================================================
# Error paths
# =============================================================================


class TestSetErrors:
    def test_no_config_option_errors(self, runner) -> None:
        result = runner.invoke(cli, ["set", "k", "v"])
        assert result.exit_code == 1
        assert "--config" in result.stderr
        assert "must be provided" in result.stderr.lower()

    def test_missing_config_file_errors(self, runner) -> None:
        result = runner.invoke(cli, ["-c", "/nonexistent/path.json", "set", "k", "v"])
        assert result.exit_code == 1
        # Either the top-level FileNotFoundError or the set-time check fires;
        # both are valid:
        assert "not found" in result.stderr.lower()

    def test_unsupported_extension_errors(self, runner, tmp_path) -> None:
        """A file with .yaml extension can't be read by ``set`` since
        confy doesn't support YAML.
        """
        bad = tmp_path / "config.yaml"
        bad.write_text("{}")
        result = runner.invoke(cli, ["-c", str(bad), "set", "k", "v"])
        # The top-level cli group catches the unsupported-extension
        # error during init, exiting before the set subcommand even runs.
        assert result.exit_code == 1


# =============================================================================
# Idempotency / round-trip
# =============================================================================


class TestSetIdempotency:
    """A set followed by another get reads back the value written."""

    def test_set_then_get(self, runner, json_config) -> None:
        fp = json_config({})
        runner.invoke(cli, ["-c", fp, "set", "k", "42"])
        result = runner.invoke(cli, ["-c", fp, "get", "k"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == 42

    def test_set_then_dump(self, runner, json_config) -> None:
        fp = json_config({"existing": 1})
        runner.invoke(cli, ["-c", fp, "set", "added", '"new"'])
        result = runner.invoke(cli, ["-c", fp, "dump"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed == {"existing": 1, "added": "new"}

    def test_set_twice_overwrites(self, runner, json_config) -> None:
        fp = json_config({})
        runner.invoke(cli, ["-c", fp, "set", "k", "first"])
        runner.invoke(cli, ["-c", fp, "set", "k", "second"])
        result = runner.invoke(cli, ["-c", fp, "get", "k"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == "second"
