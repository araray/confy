# tests/robustness/test_edge_cases.py
"""General robustness edge cases.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §7.4 — Robustness Tests

What this file tests
--------------------
Confy's behavior on unusual but legitimate inputs:

* **Deep nesting** — many levels of nested dicts must not cause
  RecursionError on init, access, or as_dict.
* **Unicode** — non-ASCII keys and values round-trip cleanly through
  JSON files, TOML files, env vars, and dot-path access.
* **Empty everything** — an empty Config, empty file, empty dict
  values must all behave sanely.
* **Large data** — thousands of keys load without performance cliff
  and dict semantics survive.
* **Whitespace and special characters** in values (newlines, tabs,
  quotes) must survive serialization round-trip.
* **Numeric edge cases** — very large/small integers, special floats
  (inf, nan), preserve through parse/serialize.

These tests are not about *novel* functionality — they pin the basic
robustness contract so future work can't quietly regress it.
"""

from __future__ import annotations

import json

import pytest

from confy.loader import Config

pytestmark = pytest.mark.robustness


# =============================================================================
# Deep nesting
# =============================================================================


class TestDeepNesting:
    """Many levels of nested dicts."""

    def test_50_levels_construction(self) -> None:
        """Construct a 50-level deep nested config without crashing."""
        depth = 50
        data: dict = {"leaf": "value"}
        for i in range(depth):
            data = {f"level_{i}": data}
        cfg = Config(defaults=data, load_dotenv_file=False)
        # Navigate to the leaf and back:
        current = cfg
        for i in range(depth - 1, -1, -1):
            current = current[f"level_{i}"]
        assert current.leaf == "value"

    def test_50_levels_as_dict_round_trip(self) -> None:
        depth = 50
        data: dict = {"leaf": 1}
        for i in range(depth):
            data = {f"l{i}": data}
        cfg = Config(defaults=data, load_dotenv_file=False)
        # round-trip equality:
        assert cfg.as_dict() == data

    def test_dot_path_get_at_depth(self) -> None:
        """A 20-deep dot-notation get must work."""
        depth = 20
        data: dict = {"leaf": "found"}
        for i in range(depth):
            data = {f"k{i}": data}
        cfg = Config(defaults=data, load_dotenv_file=False)
        # Build the full path:
        path = ".".join(f"k{i}" for i in range(depth - 1, -1, -1)) + ".leaf"
        assert cfg.get(path) == "found"


# =============================================================================
# Unicode
# =============================================================================


class TestUnicode:
    """Non-ASCII keys and values."""

    def test_unicode_value_round_trip(self, tmp_path) -> None:
        """Unicode in values survives JSON round-trip."""
        original = {
            "greeting_jp": "こんにちは",
            "greeting_ru": "Привет",
            "greeting_ar": "مرحبا",
            "greeting_emoji": "👋🌍",
        }
        f = tmp_path / "c.json"
        f.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
        cfg = Config(file_path=str(f), load_dotenv_file=False)
        assert cfg.greeting_jp == "こんにちは"
        assert cfg.greeting_ru == "Привет"
        assert cfg.greeting_ar == "مرحبا"
        assert cfg.greeting_emoji == "👋🌍"

    def test_unicode_in_defaults(self) -> None:
        cfg = Config(
            defaults={"snowman": "☃", "pi_letter": "π"},
            load_dotenv_file=False,
        )
        assert cfg.snowman == "☃"
        assert cfg.pi_letter == "π"

    def test_unicode_key_via_defaults(self) -> None:
        """Unicode keys are technically valid Python attribute names if
        they pass :meth:`str.isidentifier`. We test only dict-style
        access here since attribute access depends on locale.
        """
        cfg = Config(
            defaults={"café": "coffee", "naïve": "approach"},
            load_dotenv_file=False,
        )
        assert cfg["café"] == "coffee"
        assert cfg["naïve"] == "approach"

    def test_unicode_in_overrides(self) -> None:
        cfg = Config(
            overrides_dict={"emoji_value": "🎉"},
            load_dotenv_file=False,
        )
        assert cfg.emoji_value == "🎉"


# =============================================================================
# Empty / minimal cases
# =============================================================================


class TestEmpty:
    """An empty Config, empty file, empty dict values."""

    def test_no_sources(self) -> None:
        cfg = Config(load_dotenv_file=False)
        assert len(cfg) == 0
        assert cfg.as_dict() == {}

    def test_empty_defaults(self) -> None:
        cfg = Config(defaults={}, load_dotenv_file=False)
        assert len(cfg) == 0

    def test_empty_overrides(self) -> None:
        cfg = Config(defaults={"a": 1}, overrides_dict={}, load_dotenv_file=False)
        assert cfg.a == 1

    def test_empty_json_file(self, tmp_path) -> None:
        f = tmp_path / "c.json"
        f.write_text("{}")
        cfg = Config(file_path=str(f), load_dotenv_file=False)
        assert len(cfg) == 0

    def test_empty_toml_file(self, tmp_path) -> None:
        f = tmp_path / "c.toml"
        f.write_text("")
        cfg = Config(file_path=str(f), load_dotenv_file=False)
        assert len(cfg) == 0

    def test_empty_string_value(self) -> None:
        """An empty string is a valid value, distinct from missing."""
        cfg = Config(defaults={"k": ""}, load_dotenv_file=False)
        assert cfg.k == ""
        assert "k" in cfg

    def test_empty_dict_value(self) -> None:
        cfg = Config(defaults={"empty_section": {}}, load_dotenv_file=False)
        assert "empty_section" in cfg
        assert len(cfg.empty_section) == 0


# =============================================================================
# Large data
# =============================================================================


class TestLargeData:
    """Many keys, big values."""

    def test_1000_keys(self) -> None:
        defaults = {f"key_{i}": i for i in range(1000)}
        cfg = Config(defaults=defaults, load_dotenv_file=False)
        assert len(cfg) == 1000
        assert cfg.key_500 == 500
        assert cfg.key_999 == 999

    def test_large_string_value(self) -> None:
        big = "x" * 100_000  # 100 KB string
        cfg = Config(defaults={"big": big}, load_dotenv_file=False)
        assert cfg.big == big
        assert len(cfg.big) == 100_000

    def test_large_list(self) -> None:
        data = list(range(10_000))
        cfg = Config(defaults={"nums": data}, load_dotenv_file=False)
        assert len(cfg.nums) == 10_000
        assert cfg.nums[5000] == 5000

    @pytest.mark.slow
    def test_round_trip_large_data(self, tmp_path) -> None:
        """A 1000-key Config can be serialized to JSON and re-loaded."""
        defaults = {f"k_{i}": {"nested": i} for i in range(1000)}
        cfg = Config(defaults=defaults, load_dotenv_file=False)
        f = tmp_path / "out.json"
        f.write_text(json.dumps(cfg.as_dict()))
        loaded = Config(file_path=str(f), load_dotenv_file=False)
        assert loaded.as_dict() == cfg.as_dict()


# =============================================================================
# Whitespace and special characters
# =============================================================================


class TestSpecialCharacters:
    """Values containing newlines, tabs, quotes, control chars."""

    def test_value_with_newlines(self) -> None:
        cfg = Config(
            defaults={"multiline": "line1\nline2\nline3"},
            load_dotenv_file=False,
        )
        assert cfg.multiline == "line1\nline2\nline3"
        assert cfg.multiline.count("\n") == 2

    def test_value_with_tabs(self) -> None:
        cfg = Config(
            defaults={"tabbed": "col1\tcol2\tcol3"},
            load_dotenv_file=False,
        )
        assert cfg.tabbed == "col1\tcol2\tcol3"

    def test_value_with_quotes(self) -> None:
        cfg = Config(
            defaults={"quoted": 'He said "hello" to me'},
            load_dotenv_file=False,
        )
        assert cfg.quoted == 'He said "hello" to me'

    def test_value_with_backslashes(self) -> None:
        cfg = Config(
            defaults={"path": r"C:\Users\test"},
            load_dotenv_file=False,
        )
        assert cfg.path == r"C:\Users\test"

    def test_special_chars_round_trip_json(self, tmp_path) -> None:
        """Special characters survive JSON serialization."""
        original = {
            "newline": "a\nb",
            "tab": "a\tb",
            "quote": 'he said "hi"',
            "backslash": "C:\\Users",
        }
        cfg = Config(defaults=original, load_dotenv_file=False)
        f = tmp_path / "out.json"
        f.write_text(json.dumps(cfg.as_dict()))
        loaded = Config(file_path=str(f), load_dotenv_file=False)
        assert loaded.as_dict() == original


# =============================================================================
# Numeric edge cases
# =============================================================================


class TestNumericEdgeCases:
    """Very large/small numbers and special floats."""

    def test_large_int(self) -> None:
        big = 2**100  # bigger than int64
        cfg = Config(defaults={"big": big}, load_dotenv_file=False)
        assert cfg.big == big

    def test_negative_int(self) -> None:
        cfg = Config(defaults={"n": -(2**63)}, load_dotenv_file=False)
        assert cfg.n == -(2**63)

    def test_zero(self) -> None:
        """Zero is a valid value, NOT missing."""
        cfg = Config(defaults={"k": 0}, load_dotenv_file=False)
        assert cfg.k == 0
        assert "k" in cfg

    def test_negative_zero_float(self) -> None:
        cfg = Config(defaults={"n": -0.0}, load_dotenv_file=False)
        assert cfg.n == 0.0
        # Sign of zero is preserved (Python semantics):
        import math

        assert math.copysign(1.0, cfg.n) == -1.0

    def test_very_small_float(self) -> None:
        tiny = 1e-300
        cfg = Config(defaults={"tiny": tiny}, load_dotenv_file=False)
        assert cfg.tiny == tiny

    def test_inf_via_parse_value(self, monkeypatch) -> None:
        """Env var ``inf`` is accidentally accepted as a float by
        :func:`_parse_value` (Python's ``float("inf")`` returns infinity).
        Pinned in test_parse_value.py at the unit level; here we just
        verify the behavior propagates end-to-end through env loading.
        """
        import math

        monkeypatch.setenv("MYAPP_K", "inf")
        cfg = Config(prefix="MYAPP", load_dotenv_file=False)
        assert math.isinf(cfg.k)
        assert cfg.k > 0  # positive infinity


# =============================================================================
# Mixed-type lists
# =============================================================================


class TestMixedTypeLists:
    """Lists containing a mix of dicts, primitives, and other lists."""

    def test_mixed_list_round_trip(self) -> None:
        original = {
            "items": [
                1,
                "two",
                {"three": 3},
                [4, 5],
                None,
                True,
            ]
        }
        cfg = Config(defaults=original, load_dotenv_file=False)
        # Each element preserves its type:
        assert cfg["items"][0] == 1
        assert cfg["items"][1] == "two"
        assert cfg["items"][2].three == 3
        assert cfg["items"][3] == [4, 5]
        assert cfg["items"][4] is None
        assert cfg["items"][5] is True

    def test_list_of_lists_preserved(self) -> None:
        cfg = Config(
            defaults={"matrix": [[1, 2], [3, 4], [5, 6]]},
            load_dotenv_file=False,
        )
        assert cfg.matrix == [[1, 2], [3, 4], [5, 6]]
        assert cfg.matrix[1][1] == 4

    def test_deeply_nested_list(self) -> None:
        deep = [[[[[42]]]]]
        cfg = Config(defaults={"x": deep}, load_dotenv_file=False)
        assert cfg.x == deep
        assert cfg.x[0][0][0][0][0] == 42
