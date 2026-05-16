# tests/cli/test_cli_root.py
"""CLI top-level group tests.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §6 — CLI Specification
* ``confy/cli.py`` ``cli()`` group (lines 67-186)

What this file tests
--------------------
* ``--help`` lists all subcommands.
* ``--config`` with non-existent / parse-failing file → exit 1, error.
* ``--defaults FILE`` happy path + missing-file + bad-JSON errors.
* ``--overrides KEY:VAL,...`` parsing: JSON values, raw-string fallback,
  malformed pairs (no colon) emit a warning to stderr but don't abort.
* ``--mandatory`` triggers :class:`MissingMandatoryConfig` with a clear
  error message and exit 1.
* ``--prefix`` picks up env-var overrides.
* ``--track-provenance`` flag enables provenance tracking (verified via
  the ``provenance`` subcommand response).
* Generic init failure (e.g., unsupported file extension) is caught and
  reported as a red error with exit 1.
"""

from __future__ import annotations

import json

import pytest

from confy.cli import cli

pytestmark = pytest.mark.cli


# =============================================================================
# --help
# =============================================================================


class TestHelp:
    def test_help_lists_subcommands(self, runner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # All subcommands should appear:
        for sub in ["get", "set", "exists", "search", "dump", "convert", "provenance"]:
            assert sub in result.stdout

    def test_help_short_flag(self, runner) -> None:
        result = runner.invoke(cli, ["-h"])
        assert result.exit_code == 0
        assert "Usage" in result.stdout or "usage" in result.stdout


# =============================================================================
# --config option errors
# =============================================================================


class TestConfigOption:
    """``-c/--config FILE`` is the primary input."""

    def test_missing_file_exits_with_error(self, runner) -> None:
        result = runner.invoke(cli, ["-c", "/nonexistent/path.json", "dump"])
        assert result.exit_code == 1
        # Goes to stderr via click.secho(err=True):
        assert "not found" in result.stderr.lower()

    def test_unsupported_extension_exits_with_error(self, runner, tmp_path) -> None:
        bad = tmp_path / "config.yaml"
        bad.write_text("a: 1\n")
        result = runner.invoke(cli, ["-c", str(bad), "dump"])
        assert result.exit_code == 1
        assert (
            "unsupported" in result.stderr.lower() or "error" in result.stderr.lower()
        )

    def test_malformed_json_exits_with_error(self, runner, tmp_path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{ invalid json")
        result = runner.invoke(cli, ["-c", str(bad), "dump"])
        assert result.exit_code == 1
        assert "error" in result.stderr.lower()


# =============================================================================
# --defaults FILE
# -----------------------------------------------------------------------------
# Detailed defaults-file edge cases (malformed JSON, non-object top-level,
# path expansion quirks) live in ``test_cli_defaults_loading.py``. The root
# test file only verifies that the option is wired correctly.
# =============================================================================


class TestDefaultsWiring:
    """Minimum check that ``--defaults`` reaches the config as L1 data."""

    def test_defaults_reaches_final_config(self, runner, defaults_file) -> None:
        df = defaults_file({"defkey": "from_defaults"})
        result = runner.invoke(cli, ["--defaults", df, "dump"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed == {"defkey": "from_defaults"}


# =============================================================================
# --overrides parsing
# -----------------------------------------------------------------------------
# Detailed --overrides quirks live in ``test_cli_overrides_parsing.py`` so
# that file can focus on the parsing rules in depth. The root test file only
# verifies that the option is wired into the top-level group at all.
# =============================================================================


class TestOverridesWiring:
    """Minimum check that ``--overrides`` reaches the config layer."""

    def test_overrides_reaches_final_config(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(
            cli, ["-c", fp, "--overrides", 'a:99,added:"new"', "dump"]
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed == {"a": 99, "added": "new"}


# =============================================================================
# --mandatory
# =============================================================================


class TestMandatoryOption:
    """``--mandatory "key1,key2"`` — comma-separated dot-notation keys."""

    def test_mandatory_satisfied(self, runner, json_config) -> None:
        fp = json_config({"required": "present"})
        result = runner.invoke(cli, ["-c", fp, "--mandatory", "required", "dump"])
        assert result.exit_code == 0

    def test_mandatory_missing_errors(self, runner, json_config) -> None:
        fp = json_config({"other": "x"})
        result = runner.invoke(cli, ["-c", fp, "--mandatory", "required.key", "dump"])
        assert result.exit_code == 1
        assert "required.key" in result.stderr
        assert "missing" in result.stderr.lower()

    def test_multiple_mandatory_all_missing_listed(self, runner, json_config) -> None:
        fp = json_config({})
        result = runner.invoke(
            cli, ["-c", fp, "--mandatory", "key_a,key_b,key_c", "dump"]
        )
        assert result.exit_code == 1
        for k in ["key_a", "key_b", "key_c"]:
            assert k in result.stderr


# =============================================================================
# --prefix env var override
# =============================================================================


class TestPrefixOption:
    """``-p/--prefix MYAPP`` enables env-var overrides."""

    def test_env_var_picked_up(self, runner, json_config, monkeypatch) -> None:
        fp = json_config({"k": "from_file"})
        monkeypatch.setenv("MYAPP_K", "from_env")
        result = runner.invoke(
            cli, ["-c", fp, "--prefix", "MYAPP", "--no-dotenv", "dump"]
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed["k"] == "from_env"

    def test_no_prefix_ignores_env(self, runner, json_config, monkeypatch) -> None:
        fp = json_config({"k": "from_file"})
        monkeypatch.setenv("MYAPP_K", "from_env")
        # No --prefix: env vars ignored.
        result = runner.invoke(cli, ["-c", fp, "--no-dotenv", "dump"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed["k"] == "from_file"


# =============================================================================
# --no-dotenv flag
# =============================================================================


class TestNoDotenvFlag:
    """``--no-dotenv`` disables .env file discovery."""

    def test_disables_dotenv_search(
        self, runner, json_config, tmp_path, monkeypatch
    ) -> None:
        # Plant a .env file in cwd that would otherwise be picked up:
        env_file = tmp_path / ".env"
        env_file.write_text("MYAPP_FROM_DOTENV=should_not_appear\n")
        monkeypatch.chdir(tmp_path)
        fp = json_config({"a": 1})

        result = runner.invoke(
            cli, ["-c", fp, "--prefix", "MYAPP", "--no-dotenv", "dump"]
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert "from_dotenv" not in parsed
        assert "from" not in parsed
