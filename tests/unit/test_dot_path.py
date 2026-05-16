# tests/unit/test_dot_path.py
"""Unit tests for the dot-path helpers in :mod:`confy.loader`.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §7.2.1 — Dot-Path Tests
* ``confy/loader.py``:

  - :func:`get_by_dot` (lines 220-277)
  - :func:`set_by_dot` (lines 150-217)
  - :meth:`Config.__contains__` (lines 1290-1298)

Why this file exists
--------------------
The pre-existing ``test_loader.py`` covers the happy paths of these helpers
but leaves several branches uncovered:

* ``set_by_dot(..., create_missing=False)`` — both error directions
  (missing intermediate, missing final, non-dict segment).
* ``set_by_dot`` wrapping a plain :class:`dict` value in :class:`Config`
  when the container is a ``Config`` (line 215 in loader.py).
* ``set_by_dot`` overwriting an existing non-dict leaf with a deeper path
  (the "log a warning, replace with dict" branch).
* :meth:`Config.__contains__` returning ``False`` for invalid path types
  and short-circuiting for private/non-string keys (line 1293).
* :func:`get_by_dot` error-message contents (so a refactor doesn't silently
  weaken the error reporting that downstream code parses).
"""

from __future__ import annotations

import logging

import pytest

from confy.loader import Config, get_by_dot, set_by_dot

pytestmark = pytest.mark.unit


# =============================================================================
# get_by_dot
# =============================================================================


class TestGetByDotHappyPath:
    """Valid path traversal on dicts and Configs."""

    def test_single_segment(self) -> None:
        assert get_by_dot({"a": 1}, "a") == 1

    def test_two_segments(self) -> None:
        assert get_by_dot({"a": {"b": 2}}, "a.b") == 2

    def test_three_segments(self) -> None:
        assert get_by_dot({"a": {"b": {"c": 3}}}, "a.b.c") == 3

    def test_deeply_nested(self) -> None:
        data = {"a": {"b": {"c": {"d": {"e": {"f": 7}}}}}}
        assert get_by_dot(data, "a.b.c.d.e.f") == 7

    def test_returns_dict_when_path_targets_dict(self) -> None:
        data = {"a": {"b": {"c": 1}}}
        result = get_by_dot(data, "a.b")
        assert result == {"c": 1}

    def test_returns_list_when_path_targets_list(self) -> None:
        data = {"a": [1, 2, 3]}
        result = get_by_dot(data, "a")
        assert result == [1, 2, 3]

    def test_returns_none_when_value_is_none(self) -> None:
        """Distinguishes "key exists, value is None" from "key missing"."""
        assert get_by_dot({"a": None}, "a") is None

    def test_works_on_config(self) -> None:
        cfg = Config({"x": {"y": "found"}})
        assert get_by_dot(cfg, "x.y") == "found"


class TestGetByDotErrors:
    """Error paths — exception type AND message shape are part of the API."""

    def test_missing_top_level_raises_keyerror(self) -> None:
        with pytest.raises(KeyError) as exc:
            get_by_dot({"a": 1}, "missing")
        # The error message must include the *requested* path so callers
        # can surface it. We don't pin exact wording — only the substring
        # the user would look for.
        assert "missing" in str(exc.value)

    def test_missing_nested_raises_keyerror_with_path(self) -> None:
        with pytest.raises(KeyError) as exc:
            get_by_dot({"a": {"b": 1}}, "a.c")
        msg = str(exc.value)
        assert "a.c" in msg
        assert "c" in msg  # the missing segment

    def test_traverse_non_dict_raises_typeerror(self) -> None:
        """Per spec §7.2.1 — traversing into a scalar must be a TypeError."""
        with pytest.raises(TypeError) as exc:
            get_by_dot({"a": {"b": 1}}, "a.b.c")
        msg = str(exc.value)
        assert "b" in msg  # the segment we tried to enter
        assert "a.b" in msg  # the path that was valid up to here

    def test_traverse_list_raises_typeerror(self) -> None:
        with pytest.raises(TypeError):
            get_by_dot({"a": [1, 2]}, "a.b")

    def test_traverse_int_raises_typeerror(self) -> None:
        with pytest.raises(TypeError):
            get_by_dot({"a": 1}, "a.x")

    def test_empty_key_raises_keyerror(self) -> None:
        """Empty path → split('.') yields [''] → KeyError on '' segment."""
        with pytest.raises(KeyError):
            get_by_dot({"a": 1}, "")

    def test_pure_dot_raises_keyerror(self) -> None:
        """``'.'`` → ['' , ''] → KeyError on first empty segment."""
        with pytest.raises(KeyError):
            get_by_dot({"a": 1}, ".")

    def test_trailing_dot_on_dict_raises_keyerror(self) -> None:
        """``'a.'`` when ``'a'`` resolves to a dict: split → ``['a', '']``,
        traversal lands on the dict, then tries ``d['']`` → KeyError.
        """
        with pytest.raises(KeyError):
            get_by_dot({"a": {"b": 1}}, "a.")

    def test_trailing_dot_on_scalar_raises_typeerror(self) -> None:
        """``'a.'`` when ``'a'`` resolves to a scalar: traversal lands on
        the scalar, then tries to subscript it → TypeError. Documents the
        asymmetry: the exception class depends on the *value* at the
        prefix, not just the *shape* of the key.
        """
        with pytest.raises(TypeError):
            get_by_dot({"a": 1}, "a.")

    def test_leading_dot_raises_keyerror(self) -> None:
        """``'.a'`` → ``['', 'a']``; first iter tries ``d['']`` which is a
        KeyError regardless of what ``'a'`` would have been.
        """
        with pytest.raises(KeyError):
            get_by_dot({"a": 1}, ".a")


# =============================================================================
# set_by_dot — create_missing=True (default)
# =============================================================================


class TestSetByDotCreateMissing:
    """The default behavior: create intermediates as needed."""

    def test_single_segment_set(self) -> None:
        d: dict = {}
        set_by_dot(d, "x", 42)
        assert d == {"x": 42}

    def test_creates_nested_dict(self) -> None:
        d: dict = {}
        set_by_dot(d, "a.b.c", 1)
        assert d == {"a": {"b": {"c": 1}}}

    def test_overwrites_existing_value(self) -> None:
        d = {"a": {"b": 1}}
        set_by_dot(d, "a.b", 99)
        assert d == {"a": {"b": 99}}

    def test_overwrites_non_dict_with_dict_path(self, caplog) -> None:
        """When create_missing=True and an intermediate is a non-dict scalar,
        the implementation logs a warning and replaces with a fresh dict
        (loader.py lines 192-198).
        """
        d = {"a": 42}  # 'a' is an int, but we want to set 'a.b'
        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            set_by_dot(d, "a.b", 1)
        # The warning is informational; the important contract is that the
        # write succeeds.
        assert d == {"a": {"b": 1}}

    def test_set_dict_value_inside_config_wraps_in_config(self) -> None:
        """loader.py line 215: when the container is a Config, dict values
        must be wrapped in Config (so chained dot-notation works).
        """
        cfg = Config({"existing": 1})
        set_by_dot(cfg, "section", {"k": "v"})
        assert isinstance(cfg["section"], Config)
        assert cfg["section"]["k"] == "v"
        # Dot access works because of the wrap:
        assert cfg.section.k == "v"

    def test_set_dict_value_inside_dict_does_not_wrap(self) -> None:
        """Mirror of the above: in a plain dict, the value is just a dict."""
        d: dict = {}
        set_by_dot(d, "section", {"k": "v"})
        assert isinstance(d["section"], dict)
        assert not isinstance(d["section"], Config)


# =============================================================================
# set_by_dot — create_missing=False (currently uncovered branches)
# =============================================================================


class TestSetByDotNoCreate:
    """create_missing=False must refuse to create new dict levels."""

    def test_missing_intermediate_segment_raises_keyerror(self) -> None:
        """loader.py lines 184-185: segment not in container."""
        d = {"a": {"b": 1}}
        with pytest.raises(KeyError) as exc:
            set_by_dot(d, "x.y", 99, create_missing=False)
        assert "x" in str(exc.value)
        # Critical: d must be unchanged on error.
        assert d == {"a": {"b": 1}}

    def test_intermediate_is_non_dict_raises_typeerror(self) -> None:
        """loader.py lines 186-188: segment exists but isn't dict-like."""
        d = {"a": {"b": 1}}
        with pytest.raises(TypeError) as exc:
            set_by_dot(d, "a.b.c", 99, create_missing=False)
        msg = str(exc.value)
        assert "b" in msg
        # The implementation includes the offending segment's type.
        assert "int" in msg
        # State must not be partially mutated.
        assert d == {"a": {"b": 1}}

    def test_missing_final_key_raises_keyerror(self) -> None:
        """loader.py line 207: the path's leading parts exist, but the
        final key is absent.
        """
        d = {"a": {"b": 1}}
        with pytest.raises(KeyError) as exc:
            set_by_dot(d, "a.missing", 99, create_missing=False)
        assert "missing" in str(exc.value)
        assert d == {"a": {"b": 1}}

    def test_overwrite_existing_with_no_create_ok(self) -> None:
        """Final key exists → overwrite is allowed even when not creating."""
        d = {"a": {"b": 1}}
        set_by_dot(d, "a.b", 42, create_missing=False)
        assert d == {"a": {"b": 42}}

    def test_no_create_works_on_config(self) -> None:
        cfg = Config({"a": Config({"b": 1})})
        with pytest.raises(KeyError):
            set_by_dot(cfg, "a.missing", 99, create_missing=False)
        # Overwrite still works:
        set_by_dot(cfg, "a.b", 99, create_missing=False)
        assert cfg.a.b == 99


# =============================================================================
# Config.__contains__ (uses get_by_dot under the hood)
# =============================================================================


class TestConfigContains:
    """``'x' in cfg`` uses dot-path semantics for str keys, super() otherwise."""

    def test_top_level_present(self) -> None:
        cfg = Config({"a": 1})
        assert "a" in cfg

    def test_top_level_missing(self) -> None:
        cfg = Config({"a": 1})
        assert "missing" not in cfg

    def test_nested_present(self) -> None:
        cfg = Config({"a": {"b": {"c": 1}}})
        assert "a.b.c" in cfg

    def test_nested_missing(self) -> None:
        cfg = Config({"a": {"b": 1}})
        assert "a.b.missing" not in cfg

    def test_traversal_into_scalar_is_false(self) -> None:
        """Asking ``'a.b' in cfg`` when ``a`` is a scalar must be False
        (the get raises TypeError, which __contains__ swallows).
        """
        cfg = Config({"a": 42})
        assert "a.b" not in cfg

    def test_value_of_none_still_present(self) -> None:
        """Key with value None must still be reported present."""
        cfg = Config({"a": None})
        assert "a" in cfg

    def test_private_key_uses_super(self) -> None:
        """loader.py line 1292-1293: keys starting with '_' bypass
        get_by_dot and consult super().__contains__ directly. We probe this
        by inserting a leading-underscore key into the underlying dict.
        """
        cfg = Config()
        # Inject via dict[] (avoids __setattr__ wrapping logic)
        dict.__setitem__(cfg, "_private", 1)
        assert "_private" in cfg
        # And one that isn't there:
        assert "_other_private" not in cfg

    def test_non_string_key_uses_super(self) -> None:
        """A non-str key must not crash the dot-notation path."""
        cfg = Config()
        dict.__setitem__(cfg, 42, "int_key_value")  # type: ignore[index]
        assert 42 in cfg
        assert 99 not in cfg
