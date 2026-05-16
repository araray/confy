# tests/cli/test_cli_search.py
"""CLI ``search`` subcommand tests.

Specification reference
-----------------------
* ``confy/cli.py`` ``search()`` (lines 303-352)
* ``confy/cli.py`` ``_match()`` (lines 21-45)
* ``confy/cli.py`` ``_flatten()`` (lines 48-63)

What ``search`` does
--------------------
Searches the flattened final config for keys and/or values matching a
pattern. The pattern syntax is auto-detected:

1. **Glob** if the pattern contains any of ``*?[]`` — uses :mod:`fnmatch`
   case-insensitively (the ``-i`` flag has no extra effect here).
2. **Regex** if the pattern contains regex-special characters
   ``[.^$*+?{}\\|()[]]`` AND wasn't classified as glob (i.e., none of
   ``*?[]`` present). The ``-i`` flag enables :data:`re.IGNORECASE`.
3. **Exact** match otherwise (case-insensitive).

Subtle dispatch rule
--------------------
Because ``*``, ``?``, ``[``, and ``]`` appear in BOTH glob and regex
character sets, but the glob check fires first, any pattern containing
those characters is classified as **glob** — even if you intended a
regex like ``^foo.*$`` (which has both ``^``, ``$`` AND ``*``: glob
wins). Pure regex patterns are limited to those using only ``^$+|()``
plus alphanumerics. Tests in this file pin this behavior.
"""

from __future__ import annotations

import json

import pytest

from confy.cli import cli

pytestmark = pytest.mark.cli


# =============================================================================
# Glob matching
# =============================================================================


class TestSearchGlob:
    """Patterns with ``*?[]`` use fnmatch (case-insensitive)."""

    def test_star_wildcard(self, runner, json_config) -> None:
        fp = json_config({"db_host": "h", "db_port": 5432, "logging": "INFO"})
        result = runner.invoke(cli, ["-c", fp, "search", "--key", "db*"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert "db_host" in parsed
        assert "db_port" in parsed
        assert "logging" not in parsed

    def test_question_mark(self, runner, json_config) -> None:
        fp = json_config({"a1": 1, "a2": 2, "abc": 3})
        result = runner.invoke(cli, ["-c", fp, "search", "--key", "a?"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        # Only single-char-after-'a' keys:
        assert set(parsed.keys()) == {"a1", "a2"}

    def test_character_class(self, runner, json_config) -> None:
        fp = json_config({"a": 1, "b": 2, "c": 3, "d": 4})
        result = runner.invoke(cli, ["-c", fp, "search", "--key", "[abc]"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert set(parsed.keys()) == {"a", "b", "c"}

    def test_glob_case_insensitive_by_default(self, runner, json_config) -> None:
        """fnmatch in confy's ``_match`` lowercases both sides, so glob
        is always case-insensitive regardless of ``-i``.
        """
        fp = json_config({"DB_HOST": "x"})
        result = runner.invoke(cli, ["-c", fp, "search", "--key", "db*"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert "DB_HOST" in parsed


# =============================================================================
# Regex matching
# =============================================================================


class TestSearchRegex:
    """Patterns with regex-special chars but no ``*?[]`` use re.search."""

    def test_anchors_only(self, runner, json_config) -> None:
        """``^something$`` uses regex (only contains ``^$``)."""
        fp = json_config({"db_host": "x", "db_port": 5432, "other": "y"})
        result = runner.invoke(cli, ["-c", fp, "search", "--key", "^db_host$"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert set(parsed.keys()) == {"db_host"}

    def test_alternation(self, runner, json_config) -> None:
        """``a|b`` is regex (contains ``|``)."""
        fp = json_config({"alpha": 1, "beta": 2, "gamma": 3})
        result = runner.invoke(cli, ["-c", fp, "search", "--key", "alpha|gamma"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert set(parsed.keys()) == {"alpha", "gamma"}

    def test_regex_case_sensitive_by_default(self, runner, json_config) -> None:
        """Without ``-i``, regex is case-sensitive."""
        fp = json_config({"ALPHA": 1, "alpha": 2})
        result = runner.invoke(cli, ["-c", fp, "search", "--key", "^alpha$"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        # Only the lowercase one matches:
        assert set(parsed.keys()) == {"alpha"}

    def test_regex_case_insensitive_with_flag(self, runner, json_config) -> None:
        """``-i`` enables ``re.IGNORECASE``."""
        fp = json_config({"ALPHA": 1, "alpha": 2})
        result = runner.invoke(cli, ["-c", fp, "search", "--key", "^alpha$", "-i"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert set(parsed.keys()) == {"ALPHA", "alpha"}


# =============================================================================
# Exact matching
# =============================================================================


class TestSearchExact:
    """Patterns without any special chars do an exact (case-insensitive)
    match.
    """

    def test_exact(self, runner, json_config) -> None:
        fp = json_config({"foo": 1, "foobar": 2, "bar": 3})
        result = runner.invoke(cli, ["-c", fp, "search", "--key", "foo"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        # Only the exact match:
        assert set(parsed.keys()) == {"foo"}

    def test_exact_case_insensitive(self, runner, json_config) -> None:
        fp = json_config({"FOO": 1, "foo": 2})
        result = runner.invoke(cli, ["-c", fp, "search", "--key", "foo"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert set(parsed.keys()) == {"FOO", "foo"}

    def test_invalid_regex_falls_through_to_exact(self, runner, json_config) -> None:
        """Lines 40-42 in cli.py: a pattern that *looks* like regex
        (contains regex-special chars but no glob chars) but isn't a
        valid regex (e.g., unclosed group ``(unclosed``) falls through
        to exact matching rather than raising.
        """
        fp = json_config({"(unclosed": 1, "other": 2})
        result = runner.invoke(cli, ["-c", fp, "search", "--key", "(unclosed"])
        # The literal key '(unclosed' matches exactly (case-insensitive):
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert "(unclosed" in parsed


# =============================================================================
# Value matching
# =============================================================================


class TestSearchByValue:
    """``--val PATTERN`` matches against the string-coerced value."""

    def test_value_exact(self, runner, json_config) -> None:
        fp = json_config({"a": "match", "b": "other", "c": "match"})
        result = runner.invoke(cli, ["-c", fp, "search", "--val", "match"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert set(parsed.keys()) == {"a", "c"}

    def test_value_glob(self, runner, json_config) -> None:
        fp = json_config({"a": "hello world", "b": "goodbye", "c": "hello there"})
        result = runner.invoke(cli, ["-c", fp, "search", "--val", "hello*"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert set(parsed.keys()) == {"a", "c"}

    def test_value_number_coerces_to_string(self, runner, json_config) -> None:
        """Numbers get ``str()``-ified before matching."""
        fp = json_config({"a": 5432, "b": 5433})
        result = runner.invoke(cli, ["-c", fp, "search", "--val", "5432"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed == {"a": 5432}


# =============================================================================
# Combined --key and --val
# =============================================================================


class TestSearchKeyAndVal:
    """When both --key and --val are given, BOTH must match."""

    def test_both_match(self, runner, json_config) -> None:
        fp = json_config({"db_host": "localhost", "db_port": 5432, "logging": "INFO"})
        result = runner.invoke(
            cli,
            ["-c", fp, "search", "--key", "db*", "--val", "localhost"],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed == {"db_host": "localhost"}

    def test_key_matches_but_val_does_not(self, runner, json_config) -> None:
        fp = json_config({"db_host": "localhost", "db_port": 5432})
        result = runner.invoke(
            cli, ["-c", fp, "search", "--key", "db*", "--val", "remote"]
        )
        assert result.exit_code == 1
        assert "no matches" in result.stdout.lower()


# =============================================================================
# Nested keys flatten to dot-notation
# =============================================================================


class TestSearchFlattening:
    """Nested keys appear in flattened ``a.b.c`` form in the search space."""

    def test_nested_keys_flattened(self, runner, json_config) -> None:
        fp = json_config({"db": {"host": "h", "port": 5432}})
        result = runner.invoke(cli, ["-c", fp, "search", "--key", "db.*"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert set(parsed.keys()) == {"db.host", "db.port"}

    def test_list_value_kept_as_single_entry(self, runner, json_config) -> None:
        """Line 58 in cli.py: a list value at a flattened key is NOT
        further expanded. It appears as a single entry whose value is
        the list. (No per-index ``a[0]``, ``a[1]`` expansion — confy
        doesn't claim that.)
        """
        fp = json_config({"my_list": [1, 2, 3], "other": "x"})
        result = runner.invoke(cli, ["-c", fp, "search", "--key", "my_list"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed == {"my_list": [1, 2, 3]}


# =============================================================================
# Error paths
# =============================================================================


class TestSearchErrors:
    def test_no_pattern_errors(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(cli, ["-c", fp, "search"])
        assert result.exit_code == 1
        assert "supply" in result.stderr.lower()

    def test_no_matches_exit_1(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(cli, ["-c", fp, "search", "--key", "zzz_does_not_exist"])
        assert result.exit_code == 1
        assert "no matches" in result.stdout.lower()
