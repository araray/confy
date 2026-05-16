# tests/unit/test_parse_value.py
"""Unit tests for :func:`confy.loader._parse_value`.

The function under test converts string values (typically from environment
variables or override dicts) into Python types. This module exercises every
parsing branch and documents the *actual* current behavior of edge cases,
including a few accidental ones (``"inf"`` and ``"nan"`` being accepted as
floats) which are pinned here so changes will be deliberate.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §7.2.2 — Type Parsing Tests
* ``confy/loader.py`` :func:`_parse_value` (lines 280-349)

Parsing precedence (as implemented)
-----------------------------------
1. Non-string input → returned as-is (passthrough).
2. ``stripped.lower()`` in ``{"true", "false", "null"}`` → bool / None.
3. ``int(stripped)`` succeeds → int.
4. ``float(stripped)`` succeeds → float. (Side effect: ``"inf"`` and
   ``"nan"`` are accepted because Python's :func:`float` accepts them.)
5. JSON-shaped strings (``{...}``, ``[...]``, ``"..."`` of length > 1 with
   matching open/close characters) parse via :func:`json.loads`.
6. Anything else → the original raw value (whitespace preserved!).

Whitespace policy
-----------------
Comparisons in steps 2–5 operate on the *stripped* value, but the *fallback*
(step 6) returns the *original* string with all whitespace intact. This
asymmetry is intentional in the implementation; we test both directions.
"""

from __future__ import annotations

import math

import pytest

from confy.loader import _parse_value

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Booleans and null
# ---------------------------------------------------------------------------


class TestBooleansAndNull:
    """``true`` / ``false`` / ``null`` are case-insensitive and stripped."""

    @pytest.mark.parametrize(
        "raw",
        ["true", "TRUE", "True", "tRuE", " true ", "\ttrue\n", "true "],
    )
    def test_true_variants(self, raw: str) -> None:
        result = _parse_value(raw)
        # ``is True`` because we want to catch any accidental truthy-but-not-True
        # like a string "True" that wasn't actually parsed.
        assert result is True

    @pytest.mark.parametrize(
        "raw",
        ["false", "FALSE", "False", "fAlSe", " false ", "\tfalse\n"],
    )
    def test_false_variants(self, raw: str) -> None:
        assert _parse_value(raw) is False

    @pytest.mark.parametrize("raw", ["null", "NULL", "Null", "nUlL", " null "])
    def test_null_variants(self, raw: str) -> None:
        assert _parse_value(raw) is None

    @pytest.mark.parametrize(
        "raw",
        # Strings that LOOK like bools/null but aren't recognized must
        # fall through to string (or other types).
        ["truthy", "nope", "yes", "no", "nulla", "none", "None"],
    )
    def test_lookalikes_are_strings(self, raw: str) -> None:
        result = _parse_value(raw)
        assert isinstance(result, str)
        assert result == raw


# ---------------------------------------------------------------------------
# Integers
# ---------------------------------------------------------------------------


class TestIntegers:
    """Integer parsing — positive, negative, zero, leading-zero forms."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("0", 0),
            ("1", 1),
            ("42", 42),
            ("-1", -1),
            ("-17", -17),
            ("00", 0),  # Python's int("00") == 0
            ("007", 7),
            ("  42  ", 42),  # stripped before parsing
            ("+5", 5),
        ],
    )
    def test_integers(self, raw: str, expected: int) -> None:
        result = _parse_value(raw)
        assert result == expected
        # Make sure we got an actual int, not a float-cast equivalent.
        assert isinstance(result, int)
        assert not isinstance(result, bool)  # ints aren't bools here


# ---------------------------------------------------------------------------
# Floats
# ---------------------------------------------------------------------------


class TestFloats:
    """Float parsing — incl. scientific notation, ``inf``, ``nan``."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("3.14", 3.14),
            ("-2.5", -2.5),
            ("0.0", 0.0),
            ("1e5", 1e5),
            ("-2.5e10", -2.5e10),
            ("1.5e-10", 1.5e-10),
            ("  3.14  ", 3.14),
        ],
    )
    def test_finite_floats(self, raw: str, expected: float) -> None:
        result = _parse_value(raw)
        assert isinstance(result, float)
        assert result == pytest.approx(expected)

    @pytest.mark.parametrize("raw", ["inf", "Infinity", "INF", "-inf", "-Infinity"])
    def test_infinity_accepted(self, raw: str) -> None:
        """Pinned behavior: Python's :func:`float` accepts ``inf`` /
        ``Infinity``, and we inherit that. If we ever decide to reject it,
        this test must be updated deliberately.
        """
        result = _parse_value(raw)
        assert isinstance(result, float)
        assert math.isinf(result)

    @pytest.mark.parametrize("raw", ["nan", "NaN", "NAN"])
    def test_nan_accepted(self, raw: str) -> None:
        """Pinned behavior: ``nan`` is accepted as a float (NaN). Same caveat
        as :meth:`test_infinity_accepted`.
        """
        result = _parse_value(raw)
        assert isinstance(result, float)
        assert math.isnan(result)


# ---------------------------------------------------------------------------
# JSON-shaped strings
# ---------------------------------------------------------------------------


class TestJsonParsing:
    """The JSON branch fires only when the input both *starts* and *ends*
    with matching delimiters and ``len > 1``.
    """

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ('{"a": 1}', {"a": 1}),
            ("{}", {}),
            ('{"nested": {"k": "v"}}', {"nested": {"k": "v"}}),
        ],
    )
    def test_dict_literals(self, raw: str, expected: dict) -> None:
        assert _parse_value(raw) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("[1, 2, 3]", [1, 2, 3]),
            ("[]", []),
            ('["a", "b"]', ["a", "b"]),
            ("[true, false, null]", [True, False, None]),
        ],
    )
    def test_list_literals(self, raw: str, expected: list) -> None:
        assert _parse_value(raw) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ('"hello"', "hello"),
            ('""', ""),
            ('"with spaces"', "with spaces"),
        ],
    )
    def test_quoted_strings(self, raw: str, expected: str) -> None:
        """JSON-quoted strings are unquoted by :func:`json.loads`."""
        assert _parse_value(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "{invalid",  # Missing close brace
            '{"a": 1',  # Truncated dict
            "[1, 2,",  # Truncated list
            '"hello',  # Missing close quote
            '"',  # Single char — len not > 1
            "{",  # Single char
            "}",  # Doesn't start with valid open
            "[1, 2}",  # Mismatched delimiters
            '{"a": invalid}',  # Looks like dict, json.loads fails
        ],
    )
    def test_malformed_json_falls_through_to_string(self, raw: str) -> None:
        """Strings that pass the open-bracket heuristic but fail
        :func:`json.loads` (or fail the close-bracket check) must fall
        through to the raw-string fallback — never raise.
        """
        result = _parse_value(raw)
        assert result == raw  # unchanged, including any whitespace


# ---------------------------------------------------------------------------
# Plain strings
# ---------------------------------------------------------------------------


class TestPlainStrings:
    """Inputs that don't match any structured branch are passed through."""

    @pytest.mark.parametrize(
        "raw",
        [
            "hello",
            "plain string",
            "/path/to/file.toml",
            "http://example.com/api",
            "key=value",
            "1.2.3",  # Not a valid float (two dots) → string
            "1,000",  # Comma — not a number to int()/float()
            "12abc",  # Mixed
            "",  # Empty
            "   ",  # Whitespace only
            "  hello  ",  # Whitespace *preserved* in fallback
        ],
    )
    def test_passthrough(self, raw: str) -> None:
        assert _parse_value(raw) == raw

    def test_whitespace_preserved_in_fallback(self) -> None:
        """The implementation strips for *comparison* but returns *original*
        in the fallback branch. This is the asymmetry that distinguishes
        ``"  true  "`` (→ True, structured branch) from ``"  hello  "``
        (→ ``"  hello  "``, fallback branch).
        """
        assert _parse_value("  hello  ") == "  hello  "
        assert _parse_value("\thello\n") == "\thello\n"


# ---------------------------------------------------------------------------
# Non-string passthrough
# ---------------------------------------------------------------------------


class TestNonStringPassthrough:
    """Anything that's not a :class:`str` is returned unchanged.

    The function's first check is ``not isinstance(raw_value, str)``, so this
    short-circuits before any parsing logic. Important for use inside
    ``_collect_env_vars`` (always str) AND ``_structure_overrides`` (which
    may pass already-typed values from an ``overrides_dict``).
    """

    @pytest.mark.parametrize(
        "value",
        [
            None,
            42,
            3.14,
            True,
            False,
            [1, 2, 3],
            {"a": 1},
            (1, 2),
            b"bytes",
        ],
    )
    def test_passthrough_non_string(self, value) -> None:
        result = _parse_value(value)
        # Identity is acceptable here — the function isn't required to deep
        # copy, and the docstring documents "returned directly".
        assert result is value or result == value
        assert type(result) is type(value)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Parsing a parsed value should be a no-op (modulo type changes)."""

    @pytest.mark.parametrize(
        "raw",
        ["true", "42", "3.14", '{"a": 1}', "[1,2,3]", "hello", "null"],
    )
    def test_double_parse_stable(self, raw: str) -> None:
        once = _parse_value(raw)
        twice = _parse_value(once)
        # For non-string second-pass values, the non-string passthrough
        # branch returns them unchanged.
        assert twice == once or (
            isinstance(once, float) and math.isnan(once) and math.isnan(twice)
        )
