# tests/cli/test_cli_defaults_loading.py
"""Detailed ``--defaults FILE`` loading tests.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §6 — CLI Specification
* ``confy/cli.py`` ``cli()`` defaults-loading block (lines 108-127)

What ``--defaults`` does
------------------------
Accepts a path to a JSON file. The file is read with :func:`json.load`
and the resulting object is passed to :class:`confy.Config` as the
``defaults=...`` argument (the L1 precedence layer). Any subsequent
``--config`` / env / ``--overrides`` data is merged on top.

Why this file exists
--------------------
The defaults-loading block has its own error handling distinct from the
top-level Config init, plus several non-obvious edge cases:

* Path expansion does **NOT** apply (unlike ``--config``), so ``~/foo``
  is treated as a literal directory name.
* Non-object JSON top-level (``[1, 2, 3]``, ``"text"``, ``42``) crashes
  with a confusing message (``'X' object has no attribute 'items'``)
  because :class:`Config` expects a dict.
* ``null`` is silently accepted and treated as empty defaults.
* Bad JSON, missing files, and (on POSIX) permission errors each take
  different code paths in cli.py.

Each behavior is pinned with a focused test. Some of these (the path-
expansion gap and the non-object error message) are documented as UX
issues for follow-up rather than as desired behavior.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

from confy.cli import cli

pytestmark = pytest.mark.cli


# =============================================================================
# Happy paths
# =============================================================================


class TestBasicLoading:
    """Defaults loaded successfully appear in the merged config."""

    def test_loads_simple_dict(self, runner, defaults_file) -> None:
        df = defaults_file({"defkey": "from_defaults"})
        result = runner.invoke(cli, ["--defaults", df, "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"defkey": "from_defaults"}

    def test_loads_nested_dict(self, runner, defaults_file) -> None:
        df = defaults_file({"db": {"host": "h", "port": 5432}})
        result = runner.invoke(cli, ["--defaults", df, "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"db": {"host": "h", "port": 5432}}

    def test_loads_mixed_types(self, runner, defaults_file) -> None:
        content = {
            "string": "x",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "null": None,
            "list": [1, 2, 3],
            "nested": {"a": "b"},
        }
        df = defaults_file(content)
        result = runner.invoke(cli, ["--defaults", df, "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == content

    def test_empty_object(self, runner, defaults_file) -> None:
        """``{}`` is a valid empty defaults set, not an error."""
        df = defaults_file({})
        result = runner.invoke(cli, ["--defaults", df, "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {}


# =============================================================================
# Missing / unreadable file
# =============================================================================


class TestMissingFile:
    """A missing defaults file is an exit-1 error with a clear message."""

    def test_missing_file(self, runner) -> None:
        result = runner.invoke(
            cli, ["--defaults", "/nonexistent/dir/defaults.json", "dump"]
        )
        assert result.exit_code == 1
        # The CLI-specific message (NOT the generic Config error):
        assert "defaults file not found" in result.stderr.lower()
        # And the offending path is mentioned for debugging:
        assert "/nonexistent/dir/defaults.json" in result.stderr

    def test_missing_file_with_explicit_extension(self, runner) -> None:
        """Even with a recognizable extension, missing file → error."""
        result = runner.invoke(
            cli, ["--defaults", "/tmp/does_not_exist_xyz_12345.json", "dump"]
        )
        assert result.exit_code == 1
        assert "not found" in result.stderr.lower()


# =============================================================================
# Malformed JSON
# =============================================================================


class TestMalformedFile:
    """A defaults file that exists but contains invalid JSON should
    fail with a parsing-error message and exit code 1.
    """

    def test_unparseable_json(self, runner, tmp_path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{ not valid json")
        result = runner.invoke(cli, ["--defaults", str(bad), "dump"])
        assert result.exit_code == 1
        # The CLI surface includes the word "parsing" in its message
        # for JSON-decode errors (line 122 in cli.py):
        assert "parsing" in result.stderr.lower()

    def test_empty_file(self, runner, tmp_path) -> None:
        """An empty file → JSONDecodeError → exit 1."""
        bad = tmp_path / "empty.json"
        bad.write_text("")
        result = runner.invoke(cli, ["--defaults", str(bad), "dump"])
        assert result.exit_code == 1

    def test_trailing_garbage(self, runner, tmp_path) -> None:
        """Valid JSON followed by garbage is still invalid."""
        bad = tmp_path / "trailing.json"
        bad.write_text('{"k": 1}garbage')
        result = runner.invoke(cli, ["--defaults", str(bad), "dump"])
        assert result.exit_code == 1


# =============================================================================
# Non-object top-level (the UX hazard)
# =============================================================================


class TestNonObjectTopLevel:
    """JSON allows arrays, strings, numbers, and booleans as top-level
    values. confy's :class:`Config` only accepts a dict for defaults,
    so non-object top-levels crash with::

        Error initializing configuration: 'X' object has no attribute 'items'

    This error message is **confusing for end users** — it leaks an
    internal type name and doesn't suggest the fix. We pin the current
    behavior here, but flag it as a UX issue. A future enhancement
    should detect non-dict input and raise a user-friendly message in
    the defaults-loading block.
    """

    def test_top_level_array_crashes(self, runner, tmp_path) -> None:
        bad = tmp_path / "array.json"
        bad.write_text("[1, 2, 3]")
        result = runner.invoke(cli, ["--defaults", str(bad), "dump"])
        # Crashes — exit 1 from the generic exception handler:
        assert result.exit_code == 1
        # The leaked internal error message:
        assert "object has no attribute 'items'" in result.stderr

    def test_top_level_string_crashes(self, runner, tmp_path) -> None:
        bad = tmp_path / "string.json"
        bad.write_text('"just a string"')
        result = runner.invoke(cli, ["--defaults", str(bad), "dump"])
        assert result.exit_code == 1
        assert "object has no attribute 'items'" in result.stderr

    def test_top_level_number_crashes(self, runner, tmp_path) -> None:
        bad = tmp_path / "number.json"
        bad.write_text("42")
        result = runner.invoke(cli, ["--defaults", str(bad), "dump"])
        assert result.exit_code == 1
        assert "object has no attribute 'items'" in result.stderr

    def test_top_level_bool_crashes(self, runner, tmp_path) -> None:
        bad = tmp_path / "bool.json"
        bad.write_text("true")
        result = runner.invoke(cli, ["--defaults", str(bad), "dump"])
        assert result.exit_code == 1
        assert "object has no attribute 'items'" in result.stderr


# =============================================================================
# null top-level (silently accepted as empty)
# =============================================================================


class TestNullTopLevel:
    """A defaults file containing just ``null`` does NOT crash — it's
    silently coerced to empty defaults.

    The mechanism: :func:`json.load` returns Python ``None``. The
    :class:`Config` constructor accepts ``defaults=None`` (its default),
    which is treated as "no defaults supplied". So the merged config
    is whatever the other sources provide; in isolation, it's empty.

    Whether this should warn instead is debatable — pinning the
    current behavior.
    """

    def test_null_yields_empty_config(self, runner, tmp_path) -> None:
        df = tmp_path / "nul.json"
        df.write_text("null")
        result = runner.invoke(cli, ["--defaults", str(df), "dump"])
        assert result.exit_code == 0
        # No defaults applied; merged config is empty:
        assert json.loads(result.stdout) == {}
        # And no warning fired:
        assert result.stderr == ""

    def test_null_with_overrides_still_works(self, runner, tmp_path) -> None:
        """``null`` defaults + ``--overrides`` → the overrides apply
        normally on top of empty defaults.
        """
        df = tmp_path / "nul.json"
        df.write_text("null")
        result = runner.invoke(
            cli,
            ["--defaults", str(df), "--overrides", 'k:"v"', "dump"],
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"k": "v"}


# =============================================================================
# Path expansion (or lack thereof)
# =============================================================================


class TestPathExpansion:
    """``--defaults`` does NOT apply :func:`os.path.expanduser` to its
    argument, unlike ``--config`` (which does, via the loader). This is
    an inconsistency between the two options.

    We pin the current behavior here so an intentional fix has to
    update these tests.
    """

    def test_tilde_path_not_expanded(self, runner, tmp_path) -> None:
        """``~/foo.json`` is treated as a literal path (no expansion),
        so it fails with "not found" even if ``$HOME/foo.json`` exists.
        """
        # Plant a file at $HOME/_confy_test_defaults.json by setting
        # HOME via env injection:
        df = tmp_path / "_confy_test_defaults.json"
        df.write_text(json.dumps({"k": "from_tilde"}))

        result = runner.invoke(
            cli,
            ["--defaults", "~/_confy_test_defaults.json", "dump"],
            env={"HOME": str(tmp_path)},
        )
        # Currently fails — the ~ is not expanded. If this test starts
        # to PASS, someone added expansion logic; update or remove the
        # test accordingly.
        assert result.exit_code == 1
        assert "not found" in result.stderr.lower()

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="POSIX-style env var expansion check",
    )
    def test_env_var_in_path_not_expanded(self, runner, tmp_path) -> None:
        """``$VAR/foo.json`` is also not expanded — same gap."""
        df = tmp_path / "vendor.json"
        df.write_text(json.dumps({"k": "v"}))

        result = runner.invoke(
            cli,
            ["--defaults", "$MYVAR/vendor.json", "dump"],
            env={"MYVAR": str(tmp_path)},
        )
        assert result.exit_code == 1
        assert "not found" in result.stderr.lower()


# =============================================================================
# Precedence: defaults vs other layers
# =============================================================================


class TestPrecedenceWithOtherSources:
    """The defaults layer (L1) is the lowest precedence — every other
    source can override it. Verified end-to-end via the CLI.
    """

    def test_file_overrides_defaults(self, runner, defaults_file, json_config) -> None:
        df = defaults_file({"k": "from_defaults", "only_def": 1})
        fp = json_config({"k": "from_file", "only_file": 2})
        result = runner.invoke(cli, ["--defaults", df, "-c", fp, "dump"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        # File wins on the shared key:
        assert parsed["k"] == "from_file"
        # Unique keys from each source survive:
        assert parsed["only_def"] == 1
        assert parsed["only_file"] == 2

    def test_env_overrides_defaults(self, runner, defaults_file, monkeypatch) -> None:
        df = defaults_file({"k": "from_defaults"})
        monkeypatch.setenv("MYAPP_K", "from_env")
        result = runner.invoke(
            cli,
            [
                "--defaults",
                df,
                "--prefix",
                "MYAPP",
                "--no-dotenv",
                "dump",
            ],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed["k"] == "from_env"

    def test_overrides_dict_beats_defaults(self, runner, defaults_file) -> None:
        df = defaults_file({"k": "from_defaults"})
        result = runner.invoke(
            cli,
            ["--defaults", df, "--overrides", 'k:"from_overrides"', "dump"],
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout)["k"] == "from_overrides"

    def test_mandatory_satisfied_by_defaults(self, runner, defaults_file) -> None:
        """``--mandatory`` checks the final merged config; a key
        supplied only by defaults is enough to satisfy it.
        """
        df = defaults_file({"required": "x"})
        result = runner.invoke(
            cli, ["--defaults", df, "--mandatory", "required", "dump"]
        )
        assert result.exit_code == 0

    def test_mandatory_not_satisfied_by_missing_default(
        self, runner, defaults_file
    ) -> None:
        df = defaults_file({"other": 1})
        result = runner.invoke(
            cli, ["--defaults", df, "--mandatory", "required", "dump"]
        )
        assert result.exit_code == 1
        assert "required" in result.stderr


# =============================================================================
# Coexistence with --config
# =============================================================================


class TestNoConfigFile:
    """``--defaults`` works standalone, with no ``-c`` file."""

    def test_defaults_only_no_config(self, runner, defaults_file) -> None:
        df = defaults_file({"only_def": "x"})
        result = runner.invoke(cli, ["--defaults", df, "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"only_def": "x"}

    def test_get_works_with_defaults_only(self, runner, defaults_file) -> None:
        df = defaults_file({"k": "v"})
        result = runner.invoke(cli, ["--defaults", df, "get", "k"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == "v"

    def test_exists_works_with_defaults_only(self, runner, defaults_file) -> None:
        df = defaults_file({"k": "v"})
        result = runner.invoke(cli, ["--defaults", df, "exists", "k"])
        assert result.exit_code == 0
