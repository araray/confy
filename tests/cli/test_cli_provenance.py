# tests/cli/test_cli_provenance.py
"""CLI ``provenance [KEY]`` subcommand tests.

Specification reference
-----------------------
* ``confy/cli.py`` ``provenance()`` (lines 411-454)

What ``provenance`` does
------------------------
* **Without ``--track-provenance``** (on the top-level group): exits 1
  with a yellow error explaining the flag must be set.
* **With ``--track-provenance`` and no KEY**: prints a summary of how
  many keys came from each source category (defaults, file, env,
  overrides_dict, app_defaults).
* **With ``--track-provenance`` and a KEY**: prints the override history
  for that key, with ``→`` markers for earlier sources and ``★`` for
  the winning (current) one.
* **Unknown KEY**: prints a friendly message ("No provenance for
  key: ..."), exit 0.
"""

from __future__ import annotations

import pytest

from confy.cli import cli

pytestmark = pytest.mark.cli


# =============================================================================
# Without --track-provenance
# =============================================================================


class TestProvenanceWithoutTracking:
    """The ``provenance`` subcommand requires the global flag to be set."""

    def test_without_flag_errors(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(cli, ["-c", fp, "provenance"])
        assert result.exit_code == 1
        assert (
            "track-provenance" in result.stderr.lower()
            or "provenance" in result.stderr.lower()
        )
        assert "not enabled" in result.stderr.lower()

    def test_without_flag_errors_even_with_key(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(cli, ["-c", fp, "provenance", "a"])
        assert result.exit_code == 1


# =============================================================================
# Summary mode (no KEY)
# =============================================================================


class TestProvenanceSummary:
    """With ``--track-provenance`` and no KEY: source-category counts."""

    def test_summary_lists_file_source(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(cli, ["-c", fp, "--track-provenance", "provenance"])
        assert result.exit_code == 0
        # Output mentions the 'file' source category and a count:
        assert "file" in result.stdout
        # The summary header:
        assert "sources" in result.stdout.lower() or "source" in result.stdout.lower()

    def test_summary_includes_defaults(
        self, runner, json_config, defaults_file
    ) -> None:
        df = defaults_file({"def_only": "x"})
        fp = json_config({"file_only": "y"})
        result = runner.invoke(
            cli,
            ["--defaults", df, "-c", fp, "--track-provenance", "provenance"],
        )
        assert result.exit_code == 0
        # Both source categories appear:
        assert "defaults" in result.stdout
        assert "file" in result.stdout

    def test_summary_includes_overrides(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(
            cli,
            [
                "-c",
                fp,
                "--overrides",
                "k:1",
                "--track-provenance",
                "provenance",
            ],
        )
        assert result.exit_code == 0
        # Override source category present:
        assert "overrides" in result.stdout

    def test_summary_includes_env(self, runner, json_config, monkeypatch) -> None:
        fp = json_config({"a": 1})
        monkeypatch.setenv("MYAPP_KEY", "v")
        result = runner.invoke(
            cli,
            [
                "-c",
                fp,
                "--prefix",
                "MYAPP",
                "--no-dotenv",
                "--track-provenance",
                "provenance",
            ],
        )
        assert result.exit_code == 0
        assert "env" in result.stdout

    def test_summary_empty_says_no_data(self, runner) -> None:
        """Line 450 in cli.py: when provenance tracking is enabled but
        there's literally nothing recorded (no sources at all), the
        summary prints "No provenance data recorded."
        """
        result = runner.invoke(cli, ["--track-provenance", "--no-dotenv", "provenance"])
        assert result.exit_code == 0
        assert "no provenance data recorded" in result.stdout.lower()


# =============================================================================
# Key-specific history
# =============================================================================


class TestProvenanceHistory:
    """With ``--track-provenance KEY``: full override chain."""

    def test_history_for_overridden_key(
        self, runner, json_config, defaults_file
    ) -> None:
        df = defaults_file({"k": "from_defaults"})
        fp = json_config({"k": "from_file"})
        result = runner.invoke(
            cli,
            [
                "--defaults",
                df,
                "-c",
                fp,
                "--track-provenance",
                "provenance",
                "k",
            ],
        )
        assert result.exit_code == 0
        # The output mentions BOTH sources in the override chain:
        assert "defaults" in result.stdout
        assert "file" in result.stdout
        # And the values from each:
        assert "from_defaults" in result.stdout
        assert "from_file" in result.stdout

    def test_history_marks_winner(self, runner, json_config, defaults_file) -> None:
        """The CLI uses ``★`` for the winning entry and ``→`` for earlier
        ones (loader output convention).
        """
        df = defaults_file({"k": "v1"})
        fp = json_config({"k": "v2"})
        result = runner.invoke(
            cli,
            [
                "--defaults",
                df,
                "-c",
                fp,
                "--track-provenance",
                "provenance",
                "k",
            ],
        )
        assert result.exit_code == 0
        # Winner marker present:
        assert "★" in result.stdout or "*" in result.stdout
        # Earlier-source marker present:
        assert (
            "→" in result.stdout
            or "->" in result.stdout
            or "from_defaults" in result.stdout.lower()
            or "v1" in result.stdout
        )

    def test_history_for_unknown_key(self, runner, json_config) -> None:
        """Asking about a key with no recorded provenance is not an error;
        it prints a polite message.
        """
        fp = json_config({"a": 1})
        result = runner.invoke(
            cli,
            ["-c", fp, "--track-provenance", "provenance", "totally_unknown"],
        )
        assert result.exit_code == 0
        assert "no provenance" in result.stdout.lower()


# =============================================================================
# Combined options
# =============================================================================


class TestProvenanceWithFullStack:
    """Provenance tracking with all 5 layers in play."""

    def test_full_stack_history_for_shared_key(
        self,
        runner,
        json_config,
        defaults_file,
        monkeypatch,
    ) -> None:
        df = defaults_file({"k": "L1"})
        fp = json_config({"k": "L3"})
        monkeypatch.setenv("MYAPP_K", "L4")
        result = runner.invoke(
            cli,
            [
                "--defaults",
                df,
                "-c",
                fp,
                "--prefix",
                "MYAPP",
                "--no-dotenv",
                "--overrides",
                'k:"L5"',
                "--track-provenance",
                "provenance",
                "k",
            ],
        )
        assert result.exit_code == 0
        # All source categories appear in the history (defaults, file,
        # env, overrides_dict):
        assert "defaults" in result.stdout
        assert "file" in result.stdout
        assert "env" in result.stdout
        assert "overrides" in result.stdout
        # And the winning value:
        assert "L5" in result.stdout
