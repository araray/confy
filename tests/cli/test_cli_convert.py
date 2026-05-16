# tests/cli/test_cli_convert.py
"""CLI ``convert --to {json|toml}`` subcommand tests.

Specification reference
-----------------------
* ``confy/cli.py`` ``convert()`` (lines 363-408)

What ``convert`` does
---------------------
Re-emits the final merged config in the requested format. Output goes
to stdout by default or to a file via ``--out PATH``. The output
directory is created if it doesn't exist.
"""

from __future__ import annotations

import json
import os

import pytest
import tomli

from confy.cli import cli

pytestmark = pytest.mark.cli


# =============================================================================
# To JSON
# =============================================================================


class TestConvertToJson:
    def test_from_json_to_json_idempotent(self, runner, json_config) -> None:
        fp = json_config({"a": 1, "b": "x"})
        result = runner.invoke(cli, ["-c", fp, "convert", "--to", "json"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed == {"a": 1, "b": "x"}

    def test_from_toml_to_json(self, runner, toml_config) -> None:
        fp = toml_config('[db]\nhost = "h"\nport = 5432\n')
        result = runner.invoke(cli, ["-c", fp, "convert", "--to", "json"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed == {"db": {"host": "h", "port": 5432}}


# =============================================================================
# To TOML
# =============================================================================


class TestConvertToToml:
    def test_from_json_to_toml(self, runner, json_config) -> None:
        fp = json_config({"a": 1, "b": "x"})
        result = runner.invoke(cli, ["-c", fp, "convert", "--to", "toml"])
        assert result.exit_code == 0
        # Output should be parseable TOML:
        parsed = tomli.loads(result.stdout)
        assert parsed == {"a": 1, "b": "x"}

    def test_from_json_to_toml_nested(self, runner, json_config) -> None:
        fp = json_config({"db": {"host": "h", "port": 5432}})
        result = runner.invoke(cli, ["-c", fp, "convert", "--to", "toml"])
        assert result.exit_code == 0
        parsed = tomli.loads(result.stdout)
        assert parsed == {"db": {"host": "h", "port": 5432}}

    def test_from_toml_to_toml_idempotent(self, runner, toml_config) -> None:
        fp = toml_config('a = 1\nb = "x"\n')
        result = runner.invoke(cli, ["-c", fp, "convert", "--to", "toml"])
        assert result.exit_code == 0
        parsed = tomli.loads(result.stdout)
        assert parsed == {"a": 1, "b": "x"}


# =============================================================================
# --out file
# =============================================================================


class TestConvertWithOutFile:
    def test_write_to_file_json(self, runner, json_config, tmp_path) -> None:
        fp = json_config({"a": 1})
        out = tmp_path / "out.json"
        result = runner.invoke(
            cli, ["-c", fp, "convert", "--to", "json", "--out", str(out)]
        )
        assert result.exit_code == 0
        assert out.exists()
        with open(out) as f:
            assert json.load(f) == {"a": 1}
        # Confirmation message to stdout:
        assert str(out) in result.stdout

    def test_write_to_file_toml(self, runner, json_config, tmp_path) -> None:
        fp = json_config({"a": 1, "b": "x"})
        out = tmp_path / "out.toml"
        result = runner.invoke(
            cli, ["-c", fp, "convert", "--to", "toml", "--out", str(out)]
        )
        assert result.exit_code == 0
        with open(out, "rb") as f:
            assert tomli.load(f) == {"a": 1, "b": "x"}

    def test_creates_missing_parent_directories(
        self, runner, json_config, tmp_path
    ) -> None:
        """``--out path/sub/file.json`` creates intermediate dirs."""
        fp = json_config({"a": 1})
        out = tmp_path / "sub" / "deeper" / "out.json"
        result = runner.invoke(
            cli, ["-c", fp, "convert", "--to", "json", "--out", str(out)]
        )
        assert result.exit_code == 0
        assert out.exists()


# =============================================================================
# Errors
# =============================================================================


class TestConvertErrors:
    def test_missing_to_option(self, runner, json_config) -> None:
        """``--to`` is required."""
        fp = json_config({"a": 1})
        result = runner.invoke(cli, ["-c", fp, "convert"])
        assert result.exit_code != 0
        # Click's own error message:
        assert "to" in result.stderr.lower()

    def test_invalid_to_value(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(cli, ["-c", fp, "convert", "--to", "yaml"])
        # Click catches the invalid choice and exits with 2 (UsageError):
        assert result.exit_code != 0

    def test_to_value_case_insensitive(self, runner, json_config) -> None:
        """The ``--to`` choice is declared with ``case_sensitive=False``."""
        fp = json_config({"a": 1})
        result = runner.invoke(cli, ["-c", fp, "convert", "--to", "JSON"])
        assert result.exit_code == 0
        # Output is valid JSON:
        json.loads(result.stdout)


# =============================================================================
# Conversion with overrides
# =============================================================================


class TestConvertWithOverrides:
    """``convert`` operates on the FINAL merged config — overrides applied."""

    def test_overrides_visible_in_output(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(
            cli,
            ["-c", fp, "--overrides", "added:99", "convert", "--to", "json"],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed == {"a": 1, "added": 99}

    def test_env_vars_visible_in_output(self, runner, json_config, monkeypatch) -> None:
        fp = json_config({"a": 1})
        monkeypatch.setenv("MYAPP_FROM_ENV", "value")
        result = runner.invoke(
            cli,
            [
                "-c",
                fp,
                "--prefix",
                "MYAPP",
                "--no-dotenv",
                "convert",
                "--to",
                "json",
            ],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        # The env var landed somewhere (either nested or flat per remap):
        assert any("env" in k for k in parsed)
