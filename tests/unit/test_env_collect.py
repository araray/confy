# tests/unit/test_env_collect.py
"""Unit tests for :meth:`confy.loader.Config._collect_env_vars`.

This static method scans ``os.environ`` and produces a nested dict
according to confy's prefix-and-underscore mapping rules. It is the first
of two stages in env-var processing (the second being
``_remap_and_flatten_env_data``, tested in ``test_env_remap.py``).

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §3.3, §7.2.4 — Environment Mapping
* ``confy/loader.py`` :meth:`Config._collect_env_vars` (lines 847-970)

Mapping rules being tested
--------------------------
1. **Prefix matching is case-insensitive.** An env var ``myapp_x`` matches
   prefix ``"MYAPP"``.
2. **After prefix strip, the remainder is lowercased.**
3. **Underscore mapping**:

   - ``_`` (single)   → ``.`` (dot)
   - ``__`` (double)  → ``_`` (literal underscore)
   - Triple-underscore ``___`` (== ``__`` + ``_``) → ``_.`` (literal + dot)
4. **Prefix variants**:

   - ``None``: no env vars collected (matching disabled entirely).
   - ``""``  : all env vars collected, *except* common system vars.
   - ``"MYAPP"`` or ``"MYAPP_"`` or ``" MYAPP "``: equivalent — whitespace
     is stripped and a single trailing ``_`` is normalized into the match.
5. **Empty key after prefix strip** (e.g. env var equals ``"MYAPP_"``
   exactly) is silently skipped — line 944-945 in loader.py.
6. **Values are parsed** through ``_parse_value`` (so ``"42"`` becomes
   ``42``, ``"true"`` becomes ``True``, etc.).
"""

from __future__ import annotations

import pytest

from confy.loader import Config

pytestmark = pytest.mark.unit


# =============================================================================
# Prefix variants
# =============================================================================


class TestPrefixNone:
    """``prefix=None`` disables env-var collection entirely."""

    def test_returns_empty_dict(self, monkeypatch) -> None:
        monkeypatch.setenv("ANYTHING_AT_ALL", "x")
        assert Config._collect_env_vars(None) == {}

    def test_does_not_scan(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_KEY", "v")
        # With prefix=None, even prefixed vars are ignored.
        assert Config._collect_env_vars(None) == {}


class TestPrefixEmptyString:
    """``prefix=""`` matches all env vars except system ones."""

    def test_picks_up_non_system_vars(self, monkeypatch) -> None:
        monkeypatch.setenv("CUSTOMVAR", "v")
        result = Config._collect_env_vars("")
        assert result.get("customvar") == "v"

    @pytest.mark.parametrize(
        "system_var",
        ["HOME", "PATH", "PWD", "USER", "SHELL", "LANG", "LOGNAME"],
    )
    def test_filters_known_system_vars(self, system_var: str, monkeypatch) -> None:
        monkeypatch.setenv(system_var, "should-not-leak")
        result = Config._collect_env_vars("")
        assert system_var.lower() not in result

    def test_filters_xdg_prefix(self, monkeypatch) -> None:
        """XDG_* is a documented system prefix."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        result = Config._collect_env_vars("")
        # The "xdg" branch should not appear at all.
        assert "xdg" not in result

    def test_filters_lc_prefix(self, monkeypatch) -> None:
        """LC_* (locale) is filtered."""
        monkeypatch.setenv("LC_ALL", "C.UTF-8")
        result = Config._collect_env_vars("")
        assert "lc" not in result and "lc_all" not in result


class TestPrefixNormalization:
    """Whitespace and trailing-underscore normalization in the prefix arg."""

    def test_whitespace_stripped(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_KEY", "v")
        result = Config._collect_env_vars("  MYAPP  ")
        assert result == {"key": "v"}

    def test_trailing_underscore_normalized(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_KEY", "v")
        result = Config._collect_env_vars("MYAPP_")
        assert result == {"key": "v"}

    def test_case_insensitive_match(self, monkeypatch) -> None:
        """An uppercase prefix matches lowercased env var names."""
        monkeypatch.setenv("myapp_key", "v")  # lowercase env var
        result = Config._collect_env_vars("MYAPP")
        assert result == {"key": "v"}

    def test_prefix_exact_match_skipped(self, monkeypatch) -> None:
        """Line 944-945: an env var equal to the prefix (no key part) is
        skipped silently rather than producing an empty-key entry.
        """
        monkeypatch.setenv("MYAPP_", "should_skip")
        monkeypatch.setenv("MYAPP_REAL", "real_value")
        result = Config._collect_env_vars("MYAPP")
        # Only "real" should be present; the bare-prefix var is skipped.
        assert result == {"real": "real_value"}


# =============================================================================
# Underscore mapping
# =============================================================================


class TestUnderscoreMapping:
    """``_ → .``, ``__ → _``, ``___ → _.``"""

    def test_single_underscore_becomes_dot(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_DATABASE_HOST", "h")
        result = Config._collect_env_vars("MYAPP")
        assert result == {"database": {"host": "h"}}

    def test_double_underscore_becomes_literal_underscore(self, monkeypatch) -> None:
        """``MYAPP_FEATURE__BETA`` → key ``feature_beta`` (no further nesting)."""
        monkeypatch.setenv("MYAPP_FEATURE__BETA", "v")
        result = Config._collect_env_vars("MYAPP")
        assert result == {"feature_beta": "v"}

    def test_double_then_single(self, monkeypatch) -> None:
        """``__`` then ``_`` → literal underscore *then* dot.

        ``MYAPP_FEATURE__BETA_FLAG`` → ``feature_beta.flag``
        """
        monkeypatch.setenv("MYAPP_FEATURE__BETA_FLAG", "v")
        result = Config._collect_env_vars("MYAPP")
        assert result == {"feature_beta": {"flag": "v"}}

    def test_triple_underscore_decomposes(self, monkeypatch) -> None:
        """``___`` is parsed greedily as ``__`` + ``_`` → literal + dot.

        ``MYAPP_A___B_C`` traces as:
        - lower: ``a___b_c``
        - ``__`` → ``#TEMP#``: ``a#TEMP#_b_c`` (one ``__`` consumed)
        - ``_``  → ``.``:      ``a#TEMP#.b.c``
        - ``#TEMP#`` → ``_``:  ``a_.b.c``
        - set_by_dot → ``{"a_": {"b": {"c": "v"}}}``
        """
        monkeypatch.setenv("MYAPP_A___B_C", "v")
        result = Config._collect_env_vars("MYAPP")
        assert result == {"a_": {"b": {"c": "v"}}}

    def test_deeply_nested(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_A_B_C_D_E", "deep")
        result = Config._collect_env_vars("MYAPP")
        assert result == {"a": {"b": {"c": {"d": {"e": "deep"}}}}}


# =============================================================================
# Value parsing (via _parse_value)
# =============================================================================


class TestValueParsing:
    """Values are parsed: bools, ints, floats, JSON, fallback to str."""

    def test_string_value(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_K", "hello")
        assert Config._collect_env_vars("MYAPP") == {"k": "hello"}

    def test_int_value(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_K", "42")
        assert Config._collect_env_vars("MYAPP") == {"k": 42}

    def test_float_value(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_K", "3.14")
        result = Config._collect_env_vars("MYAPP")
        assert result["k"] == pytest.approx(3.14)

    def test_bool_value(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_K", "true")
        assert Config._collect_env_vars("MYAPP") == {"k": True}

    def test_null_value(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_K", "null")
        assert Config._collect_env_vars("MYAPP") == {"k": None}

    def test_json_list_value(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_LIST", "[1, 2, 3]")
        assert Config._collect_env_vars("MYAPP") == {"list": [1, 2, 3]}

    def test_json_dict_value(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_D", '{"a": 1}')
        assert Config._collect_env_vars("MYAPP") == {"d": {"a": 1}}

    def test_empty_string_value(self, monkeypatch) -> None:
        """Empty strings are preserved (they're a valid value)."""
        monkeypatch.setenv("MYAPP_K", "")
        assert Config._collect_env_vars("MYAPP") == {"k": ""}


# =============================================================================
# Multi-variable scenarios
# =============================================================================


class TestMultipleVars:
    """Real-world combinations of multiple env vars."""

    def test_two_unrelated_vars(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_DB_HOST", "h")
        monkeypatch.setenv("MYAPP_DB_PORT", "5432")
        assert Config._collect_env_vars("MYAPP") == {"db": {"host": "h", "port": 5432}}

    def test_two_separate_subtrees(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_DB_HOST", "h")
        monkeypatch.setenv("MYAPP_API_KEY", "secret")
        result = Config._collect_env_vars("MYAPP")
        assert result == {
            "db": {"host": "h"},
            "api": {"key": "secret"},
        }

    def test_different_prefix_ignored(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_X", "1")
        monkeypatch.setenv("OTHER_Y", "2")  # different prefix
        result = Config._collect_env_vars("MYAPP")
        assert result == {"x": 1}
        assert "y" not in result

    def test_unrelated_vars_outside_prefix(self, monkeypatch) -> None:
        monkeypatch.setenv("FOO", "bar")  # No prefix at all
        result = Config._collect_env_vars("MYAPP")
        # Should not appear with prefix="MYAPP"
        assert "foo" not in result
