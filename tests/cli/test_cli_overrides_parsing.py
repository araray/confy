# tests/cli/test_cli_overrides_parsing.py
"""Detailed ``--overrides`` parsing tests.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §6 — CLI Specification
* ``confy/cli.py`` ``cli()`` overrides-parsing block (lines 130-150)

What ``--overrides`` does
-------------------------
Accepts a single string of the form::

    KEY1:JSON_VALUE1,KEY2:JSON_VALUE2,...

It's split first on ``,`` (pair separator), then each pair is split once
on ``:`` (key/value separator). Both halves are :meth:`str.strip`-ed.
The value half is fed through :func:`json.loads`; if that fails, it's
kept as a raw string. Keys may use dot-notation.

Why this file exists
--------------------
The split-on-comma-then-split-on-colon scheme has several non-obvious
consequences worth pinning explicitly:

* **Values with embedded colons** work because ``split(":", 1)`` only
  splits on the first colon (URLs, timestamps, ratios).
* **JSON arrays and objects** are broken by the leading comma split
  (``arr:[1, 2, 3]`` becomes 3 pairs, one malformed).
* **Empty key**, **empty value**, **bare comma** all have specific
  documented behaviors (no crash, sometimes warning).
* **Whitespace** is stripped on both sides of the colon.
* **Conflicting keys** within one ``--overrides`` follow Python dict
  last-wins semantics.

Each behavior is pinned with a focused test so that any refactor of the
parser must consciously decide whether to preserve it.
"""

from __future__ import annotations

import json

import pytest

from confy.cli import cli

pytestmark = pytest.mark.cli


# =============================================================================
# Basic happy paths
# =============================================================================


class TestBasicParsing:
    """Standard cases that must keep working."""

    def test_single_pair_int_value(self, runner, json_config) -> None:
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "--overrides", "k:42", "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"k": 42}

    def test_single_pair_string_value(self, runner, json_config) -> None:
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "--overrides", 'k:"text"', "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"k": "text"}

    def test_multiple_pairs(self, runner, json_config) -> None:
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "--overrides", "a:1,b:2,c:3", "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"a": 1, "b": 2, "c": 3}

    def test_dot_notation_keys(self, runner, json_config) -> None:
        fp = json_config({"db": {"host": "x"}})
        result = runner.invoke(cli, ["-c", fp, "--overrides", 'db.host:"new"', "dump"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed["db"]["host"] == "new"

    def test_deeply_nested_dot_key(self, runner, json_config) -> None:
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "--overrides", "a.b.c.d:42", "dump"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed == {"a": {"b": {"c": {"d": 42}}}}


# =============================================================================
# JSON value-type parsing matrix
# =============================================================================


class TestValueTypeParsing:
    """The value half of each pair is fed through :func:`json.loads`. Each
    JSON scalar type must round-trip into the expected Python type. When
    JSON parsing fails, the raw string is kept (fallback).
    """

    def test_int(self, runner, json_config) -> None:
        fp = json_config({})
        r = runner.invoke(cli, ["-c", fp, "--overrides", "k:42", "dump"])
        assert json.loads(r.stdout)["k"] == 42

    def test_negative_int(self, runner, json_config) -> None:
        fp = json_config({})
        r = runner.invoke(cli, ["-c", fp, "--overrides", "k:-17", "dump"])
        assert json.loads(r.stdout)["k"] == -17

    def test_float(self, runner, json_config) -> None:
        fp = json_config({})
        r = runner.invoke(cli, ["-c", fp, "--overrides", "k:3.14", "dump"])
        assert json.loads(r.stdout)["k"] == 3.14

    def test_true(self, runner, json_config) -> None:
        fp = json_config({})
        r = runner.invoke(cli, ["-c", fp, "--overrides", "k:true", "dump"])
        assert json.loads(r.stdout)["k"] is True

    def test_false(self, runner, json_config) -> None:
        fp = json_config({})
        r = runner.invoke(cli, ["-c", fp, "--overrides", "k:false", "dump"])
        assert json.loads(r.stdout)["k"] is False

    def test_null(self, runner, json_config) -> None:
        fp = json_config({})
        r = runner.invoke(cli, ["-c", fp, "--overrides", "k:null", "dump"])
        assert json.loads(r.stdout)["k"] is None

    def test_quoted_string(self, runner, json_config) -> None:
        fp = json_config({})
        r = runner.invoke(cli, ["-c", fp, "--overrides", 'k:"hello"', "dump"])
        assert json.loads(r.stdout)["k"] == "hello"

    def test_raw_string_when_not_valid_json(self, runner, json_config) -> None:
        """Any value that doesn't parse as JSON falls back to the raw
        string verbatim (with whitespace stripped).
        """
        fp = json_config({})
        r = runner.invoke(cli, ["-c", fp, "--overrides", "k:plain", "dump"])
        assert json.loads(r.stdout)["k"] == "plain"

    def test_all_types_in_one_call(self, runner, json_config) -> None:
        fp = json_config({})
        result = runner.invoke(
            cli,
            [
                "-c",
                fp,
                "--overrides",
                'b:true,n:null,i:42,f:3.14,s:"text"',
                "dump",
            ],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed == {
            "b": True,
            "n": None,
            "i": 42,
            "f": 3.14,
            "s": "text",
        }


# =============================================================================
# Delimiter semantics: split-on-first-colon, conflicting keys
# =============================================================================


class TestDelimiterSemantics:
    """The split-on-first-colon rule lets values contain colons freely."""

    def test_url_with_port_works(self, runner, json_config) -> None:
        """``url:http://example.com:8080/path`` parses as key=``url``,
        value=``http://example.com:8080/path`` (kept as raw string,
        since the URL isn't valid JSON).
        """
        fp = json_config({})
        result = runner.invoke(
            cli,
            ["-c", fp, "--overrides", "url:http://example.com:8080/path", "dump"],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed["url"] == "http://example.com:8080/path"

    def test_value_with_multiple_colons(self, runner, json_config) -> None:
        """Time-of-day, ratios, IPv6 addresses, etc."""
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "--overrides", "t:12:34:56", "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout)["t"] == "12:34:56"

    def test_conflicting_keys_last_wins(self, runner, json_config) -> None:
        """Two pairs with the same key in one ``--overrides``: the later
        entry overwrites the earlier (standard Python dict semantics).
        """
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "--overrides", "k:1,k:2,k:3", "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"k": 3}


# =============================================================================
# Whitespace handling
# =============================================================================


class TestWhitespace:
    """Both halves of each pair are :meth:`str.strip`-ed (line 135-136
    in cli.py)."""

    def test_whitespace_around_key(self, runner, json_config) -> None:
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "--overrides", "  k  :42", "dump"])
        assert result.exit_code == 0
        # The key is stripped — no spaces in the resulting key:
        assert json.loads(result.stdout) == {"k": 42}

    def test_whitespace_around_value(self, runner, json_config) -> None:
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "--overrides", "k:  42  ", "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"k": 42}

    def test_whitespace_both_sides(self, runner, json_config) -> None:
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "--overrides", "  k  :  42  ", "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"k": 42}


# =============================================================================
# Malformed pairs
# =============================================================================


class TestMalformedPairs:
    """A pair without a colon emits a yellow warning to stderr but does
    NOT abort the command. Other pairs in the same ``--overrides``
    string are still processed.
    """

    def test_no_colon_pair_warns_and_continues(self, runner, json_config) -> None:
        fp = json_config({"a": 1})
        result = runner.invoke(cli, ["-c", fp, "--overrides", "no_colon_here", "dump"])
        assert result.exit_code == 0
        assert "malformed" in result.stderr.lower()
        # And the rest of the config still loaded:
        assert json.loads(result.stdout) == {"a": 1}

    def test_partial_failure_processes_good_pairs(self, runner, json_config) -> None:
        """When several pairs are given and one is malformed, the rest
        are still processed and the command succeeds.
        """
        fp = json_config({})
        result = runner.invoke(
            cli,
            ["-c", fp, "--overrides", "good:1,bad_no_colon,also_good:2", "dump"],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed == {"good": 1, "also_good": 2}
        assert "malformed" in result.stderr.lower()
        assert "bad_no_colon" in result.stderr

    def test_consecutive_commas_skip_empty_pair(self, runner, json_config) -> None:
        """``a:1,,b:2`` has an empty pair in the middle. The empty pair
        has no colon → treated as malformed → warning + skip.
        """
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "--overrides", "a:1,,b:2", "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"a": 1, "b": 2}
        assert "malformed" in result.stderr.lower()

    def test_trailing_comma(self, runner, json_config) -> None:
        """``a:1,`` has a trailing empty pair → warning + skip the empty
        but process the leading pair.
        """
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "--overrides", "a:1,", "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"a": 1}

    def test_leading_comma(self, runner, json_config) -> None:
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "--overrides", ",a:1", "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"a": 1}


# =============================================================================
# Empty key / empty value
# =============================================================================


class TestEmptySegments:
    """Empty key or empty value: documented behavior pinned here so
    refactors are deliberate. Neither case crashes; both result in
    unusual but defensible config state.
    """

    def test_empty_value(self, runner, json_config) -> None:
        """``k:`` parses as ``{"k": ""}`` (empty string)."""
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "--overrides", "k:", "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"k": ""}

    def test_empty_key(self, runner, json_config) -> None:
        """``:value`` parses as ``{"": "value"}`` (empty string key).
        Unusual but not a crash.
        """
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "--overrides", ":value", "dump"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"": "value"}


# =============================================================================
# Known limitation: JSON arrays/objects as values
# =============================================================================


class TestKnownLimitations:
    """The leading split-on-comma in the ``--overrides`` parser means
    JSON arrays and objects cannot be passed as ``--overrides`` values
    directly. The current behavior is preserved for backward
    compatibility, but a clean alternative now exists:

    * ``--overrides-json`` accepts a JSON object string directly and
      handles compound values (arrays, nested objects) without the
      comma-corruption problem documented below.

    These tests pin the legacy ``--overrides`` behavior so that any
    future change to the comma-split parser is deliberate. See the
    :class:`TestOverridesJson` class below for the new
    ``--overrides-json`` flag's tests.
    """

    def test_json_array_value_breaks_on_inner_commas(self, runner, json_config) -> None:
        """``arr:[1, 2, 3]`` is split by comma BEFORE colon-parsing.
        Result: 3 separate pair attempts:

        - ``"arr:[1"`` → key=arr, value="[1" (not valid JSON → raw string).
        - ``" 2"``    → no colon → warning, skipped.
        - ``" 3]"``   → no colon → warning, skipped.
        """
        fp = json_config({})
        result = runner.invoke(cli, ["-c", fp, "--overrides", "arr:[1, 2, 3]", "dump"])
        # Doesn't crash; finishes with the partial result and warnings:
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        # The "arr" key gets the truncated raw-string value:
        assert parsed["arr"] == "[1"
        # And the orphan pairs emitted warnings:
        assert result.stderr.count("Malformed") == 2

    def test_json_object_value_also_breaks(self, runner, json_config) -> None:
        """Same problem with object literals: ``d:{"a": 1, "b": 2}``
        splits on the comma. But here BOTH halves happen to contain
        colons, so neither is flagged as ``Malformed`` — instead the
        result is silently *corrupted* into two bizarre key/value
        pairs:

        - ``d:{"a": 1``   → key=``d``,    value=``{"a": 1`` (raw string)
        - `` "b": 2}``    → key=``"b"`` (after strip), value=``2}``

        This is more dangerous than the array case (silent corruption
        vs. visible warning) and is pinned here so any future syntax
        change has to consciously address it.
        """
        fp = json_config({})
        result = runner.invoke(
            cli, ["-c", fp, "--overrides", 'd:{"a": 1, "b": 2}', "dump"]
        )
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        # Corrupted shape: BOTH halves accepted as separate pairs, with
        # raw-string values that are pieces of the original JSON.
        assert parsed["d"] == '{"a": 1'
        assert parsed['"b"'] == "2}"
        # And no warning fired — the silent corruption is the hazard:
        assert "malformed" not in result.stderr.lower()


# =============================================================================
# Interaction with other sources
# =============================================================================


class TestOverridesPrecedence:
    """``--overrides`` is L5 — highest precedence. Verified via CLI."""

    def test_beats_file(self, runner, json_config) -> None:
        fp = json_config({"k": "from_file"})
        result = runner.invoke(
            cli, ["-c", fp, "--overrides", 'k:"from_overrides"', "dump"]
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout)["k"] == "from_overrides"

    def test_beats_defaults(self, runner, defaults_file) -> None:
        df = defaults_file({"k": "from_defaults"})
        result = runner.invoke(
            cli,
            ["--defaults", df, "--overrides", 'k:"from_overrides"', "dump"],
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout)["k"] == "from_overrides"

    def test_beats_env(self, runner, json_config, monkeypatch) -> None:
        fp = json_config({})
        monkeypatch.setenv("MYAPP_K", "from_env")
        result = runner.invoke(
            cli,
            [
                "-c",
                fp,
                "--prefix",
                "MYAPP",
                "--no-dotenv",
                "--overrides",
                'k:"from_overrides"',
                "dump",
            ],
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout)["k"] == "from_overrides"


# =============================================================================
# --overrides-json (I-04 fix)
# =============================================================================


class TestOverridesJson:
    """``--overrides-json`` accepts a JSON object string directly. It
    sidesteps the legacy comma-corruption problem in ``--overrides``
    by parsing the entire payload through :func:`json.loads`, so
    arrays, nested objects, and values containing commas all round-trip
    losslessly.

    Precedence: applied AFTER ``--overrides`` (last wins for conflicting
    dot-paths). Top-level keys may use dot-notation OR nested objects;
    both are normalized to dot-keyed form internally before the merge.
    """

    # ---- Happy paths --------------------------------------------------

    def test_simple_scalar(self, runner, json_config) -> None:
        fp = json_config({})
        r = runner.invoke(cli, ["-c", fp, "--overrides-json", '{"k": 42}', "dump"])
        assert r.exit_code == 0, r.stderr
        assert json.loads(r.stdout) == {"k": 42}

    def test_array_value_works(self, runner, json_config) -> None:
        """The original ``--overrides`` quirk: ``arr:[1, 2, 3]`` is
        comma-shredded. ``--overrides-json`` handles it cleanly.
        """
        fp = json_config({})
        r = runner.invoke(
            cli,
            ["-c", fp, "--overrides-json", '{"arr": [1, 2, 3]}', "dump"],
        )
        assert r.exit_code == 0, r.stderr
        assert json.loads(r.stdout) == {"arr": [1, 2, 3]}

    def test_object_value_works(self, runner, json_config) -> None:
        """Nested object value with internal commas — also works."""
        fp = json_config({})
        r = runner.invoke(
            cli,
            [
                "-c",
                fp,
                "--overrides-json",
                '{"d": {"a": 1, "b": 2}}',
                "dump",
            ],
        )
        assert r.exit_code == 0, r.stderr
        # The nested object lands at the right path:
        parsed = json.loads(r.stdout)
        assert parsed == {"d": {"a": 1, "b": 2}}

    def test_dot_key_form_at_top_level(self, runner, json_config) -> None:
        """Top-level dot-keys are equivalent to nested objects."""
        fp = json_config({})
        r = runner.invoke(
            cli,
            ["-c", fp, "--overrides-json", '{"db.host": "h1"}', "dump"],
        )
        assert r.exit_code == 0, r.stderr
        assert json.loads(r.stdout) == {"db": {"host": "h1"}}

    def test_mixed_dot_and_nested(self, runner, json_config) -> None:
        """A mix of dot-key and nested forms in one --overrides-json:
        both styles flatten to dot-keys before the merge.
        """
        fp = json_config({})
        r = runner.invoke(
            cli,
            [
                "-c",
                fp,
                "--overrides-json",
                '{"db": {"host": "h"}, "x.y": 1}',
                "dump",
            ],
        )
        assert r.exit_code == 0, r.stderr
        assert json.loads(r.stdout) == {"db": {"host": "h"}, "x": {"y": 1}}

    def test_value_with_embedded_commas(self, runner, json_config) -> None:
        """Strings containing commas pass through untouched (no shredding)."""
        fp = json_config({})
        r = runner.invoke(
            cli,
            [
                "-c",
                fp,
                "--overrides-json",
                '{"csv": "a,b,c,d"}',
                "dump",
            ],
        )
        assert r.exit_code == 0, r.stderr
        assert json.loads(r.stdout)["csv"] == "a,b,c,d"

    def test_deep_merge_preserves_siblings(self, runner, json_config) -> None:
        """Deep-merge semantics: setting ``db.host`` via
        ``--overrides-json`` does NOT wipe the sibling ``db.port``.
        """
        fp = json_config({"db": {"host": "h_old", "port": 5432}})
        r = runner.invoke(
            cli,
            [
                "-c",
                fp,
                "--overrides-json",
                '{"db": {"host": "h_new"}}',
                "dump",
            ],
        )
        assert r.exit_code == 0, r.stderr
        parsed = json.loads(r.stdout)
        assert parsed["db"]["host"] == "h_new"
        # Sibling preserved:
        assert parsed["db"]["port"] == 5432

    # ---- Error handling -----------------------------------------------

    def test_invalid_json_errors_out(self, runner, json_config) -> None:
        fp = json_config({})
        r = runner.invoke(
            cli,
            ["-c", fp, "--overrides-json", "{not valid json", "dump"],
        )
        assert r.exit_code == 1
        # Error message names the option:
        assert "--overrides-json" in r.stderr
        # No silent corruption:
        assert "parsing" in r.stderr.lower()

    def test_non_object_top_level_errors_out(self, runner, json_config) -> None:
        """Top-level must be a JSON object; arrays/scalars are rejected
        with a friendly error (I-04 parallel of I-03).
        """
        fp = json_config({})
        r = runner.invoke(cli, ["-c", fp, "--overrides-json", "[1, 2, 3]", "dump"])
        assert r.exit_code == 1
        assert "must be a JSON object" in r.stderr

    def test_non_object_string_errors_out(self, runner, json_config) -> None:
        fp = json_config({})
        r = runner.invoke(cli, ["-c", fp, "--overrides-json", '"plain"', "dump"])
        assert r.exit_code == 1
        assert "must be a JSON object" in r.stderr

    # ---- Layered precedence -------------------------------------------

    def test_overrides_json_beats_overrides_for_same_key(
        self, runner, json_config
    ) -> None:
        """When both ``--overrides`` and ``--overrides-json`` target
        the same dot-path, the JSON one wins (it is documented as
        "applied after").
        """
        fp = json_config({})
        r = runner.invoke(
            cli,
            [
                "-c",
                fp,
                "--overrides",
                'k:"from_classic"',
                "--overrides-json",
                '{"k": "from_json"}',
                "dump",
            ],
        )
        assert r.exit_code == 0, r.stderr
        assert json.loads(r.stdout)["k"] == "from_json"

    def test_overrides_json_disjoint_from_overrides(self, runner, json_config) -> None:
        """When the two options touch different keys, both contribute."""
        fp = json_config({})
        r = runner.invoke(
            cli,
            [
                "-c",
                fp,
                "--overrides",
                "a:1",
                "--overrides-json",
                '{"b": 2}',
                "dump",
            ],
        )
        assert r.exit_code == 0, r.stderr
        assert json.loads(r.stdout) == {"a": 1, "b": 2}

    def test_overrides_json_nested_vs_overrides_dotkey(
        self, runner, json_config
    ) -> None:
        """A nested form in --overrides-json conflicts with a dot-key
        form in --overrides for the same logical path. JSON one wins.
        """
        fp = json_config({})
        r = runner.invoke(
            cli,
            [
                "-c",
                fp,
                "--overrides",
                'db.host:"h_classic"',
                "--overrides-json",
                '{"db": {"host": "h_json"}}',
                "dump",
            ],
        )
        assert r.exit_code == 0, r.stderr
        assert json.loads(r.stdout)["db"]["host"] == "h_json"

    def test_overrides_json_beats_file(self, runner, json_config) -> None:
        """Same L5 (overrides) precedence as the classic --overrides."""
        fp = json_config({"k": "from_file"})
        r = runner.invoke(
            cli,
            [
                "-c",
                fp,
                "--overrides-json",
                '{"k": "from_json"}',
                "dump",
            ],
        )
        assert r.exit_code == 0, r.stderr
        assert json.loads(r.stdout)["k"] == "from_json"

    def test_overrides_json_beats_defaults(self, runner, defaults_file) -> None:
        df = defaults_file({"k": "from_defaults"})
        r = runner.invoke(
            cli,
            [
                "--defaults",
                df,
                "--overrides-json",
                '{"k": "from_json"}',
                "dump",
            ],
        )
        assert r.exit_code == 0, r.stderr
        assert json.loads(r.stdout)["k"] == "from_json"
