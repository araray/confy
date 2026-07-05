# tests/unit/test_dot_path_list_indexing.py
"""Tests for the SF-2 v1 dot-path contract additions in :mod:`confy.loader`.

Covers two additive features:

* **List-index traversal** in :func:`get_by_dot` / :func:`set_by_dot`:
  when the current node is a sequence (not ``str``/``bytes``/dict) and the
  path segment is all ASCII digits, the segment indexes into the sequence
  (e.g. ``"servers.0.host"``).
* **:func:`contains_dot`** — a non-raising existence check mirroring
  :func:`get_by_dot` traversal, exported from both ``confy.loader`` and the
  ``confy`` package root.

Just as important as the new behavior are the **regression guarantees**:
every pre-existing access pattern must behave exactly as before. In
particular:

* Dict lookup always wins on dicts — a dict with the string key ``"0"``
  is completely unaffected.
* Non-digit segments applied to a list keep their historical semantics
  (``TypeError`` on get; overwrite-with-dict / raise on set).
* ``set_by_dot`` NEVER grows or creates lists — assignment only targets an
  existing index; out-of-range raises ``KeyError`` regardless of
  ``create_missing``.
"""

from __future__ import annotations

import logging

import pytest

from confy.loader import Config, contains_dot, get_by_dot, set_by_dot

pytestmark = pytest.mark.unit


# =============================================================================
# Regression: pre-existing patterns are unchanged
# =============================================================================


class TestDictWithDigitStringKeysUnchanged:
    """A dict whose keys are digit strings must behave exactly as before."""

    def test_get_prefers_dict_key_over_index(self) -> None:
        data = {"a": {"0": "dict-key-value", "1": "other"}}
        assert get_by_dot(data, "a.0") == "dict-key-value"
        assert get_by_dot(data, "a.1") == "other"

    def test_get_missing_digit_key_on_dict_raises_keyerror(self) -> None:
        data = {"a": {"0": "x"}}
        with pytest.raises(KeyError):
            get_by_dot(data, "a.2")

    def test_set_targets_dict_key_not_index(self) -> None:
        d = {"a": {"0": 1}}
        set_by_dot(d, "a.0", 99)
        assert d == {"a": {"0": 99}}

    def test_set_creates_new_digit_dict_key(self) -> None:
        """On a dict, a previously-absent digit segment is a NEW dict key
        (never an index error), exactly as before."""
        d = {"a": {"0": 1}}
        set_by_dot(d, "a.7", "new")
        assert d == {"a": {"0": 1, "7": "new"}}

    def test_set_creates_nested_dicts_for_digit_segments(self) -> None:
        """With no list anywhere on the path, digit segments create dicts."""
        d: dict = {}
        set_by_dot(d, "x.0.y", 1)
        assert d == {"x": {"0": {"y": 1}}}

    def test_config_access_uses_dict_key(self) -> None:
        cfg = Config({"a": {"0": "from-dict"}})
        assert cfg.get("a.0") == "from-dict"
        assert "a.0" in cfg
        assert contains_dot(cfg, "a.0")


class TestNonDigitSegmentsOnListsUnchanged:
    """Historical error/overwrite semantics for non-index access on lists."""

    def test_get_non_digit_segment_on_list_raises_typeerror(self) -> None:
        with pytest.raises(TypeError):
            get_by_dot({"a": [1, 2]}, "a.b")

    def test_get_negative_index_raises_typeerror(self) -> None:
        """``-1`` is not all-digits, so it is not an index segment."""
        with pytest.raises(TypeError):
            get_by_dot({"a": [1, 2]}, "a.-1")

    def test_set_non_digit_segment_overwrites_list_when_creating(self) -> None:
        """create_missing=True: the list is clobbered with a dict (historical
        behavior, warning logged)."""
        d = {"a": [1, 2]}
        set_by_dot(d, "a.b", 5)
        assert d == {"a": {"b": 5}}

    def test_set_non_digit_segment_raises_when_not_creating(self) -> None:
        d = {"a": [1, 2]}
        with pytest.raises(TypeError):
            set_by_dot(d, "a.b", 5, create_missing=False)
        assert d == {"a": [1, 2]}

    def test_set_final_non_digit_key_after_list_parent_dict(self) -> None:
        """Plain dict/scalar paths that never touch a list are untouched."""
        d = {"a": {"b": 1}}
        set_by_dot(d, "a.c", 2)
        assert d == {"a": {"b": 1, "c": 2}}

    def test_set_through_tuple_keeps_historical_clobber(self) -> None:
        """Writes only traverse MUTABLE sequences; a tuple intermediate is
        overwritten with a dict exactly as before (create_missing=True)."""
        d = {"a": ({"b": 1},)}
        set_by_dot(d, "a.0.b", 9)
        assert d == {"a": {"0": {"b": 9}}}


class TestScalarTraversalUnchanged:
    """Scalar mid-path behavior from the existing contract is untouched."""

    def test_get_scalar_traversal_still_typeerror(self) -> None:
        with pytest.raises(TypeError):
            get_by_dot({"a": 1}, "a.b")

    def test_get_string_is_not_indexable(self) -> None:
        """Strings are sequences but must never be indexed by dot-path."""
        with pytest.raises(TypeError):
            get_by_dot({"a": "hello"}, "a.0")

    def test_set_string_is_not_indexable(self) -> None:
        """Historical behavior: scalar (str) intermediate is clobbered."""
        d = {"a": "hello"}
        set_by_dot(d, "a.0", "x")
        assert d == {"a": {"0": "x"}}


# =============================================================================
# New: list-index traversal — get_by_dot
# =============================================================================


class TestGetByDotListIndexing:
    def test_index_into_list_of_scalars(self) -> None:
        assert get_by_dot({"a": [10, 20, 30]}, "a.0") == 10
        assert get_by_dot({"a": [10, 20, 30]}, "a.2") == 30

    def test_index_into_list_of_dicts(self) -> None:
        data = {"servers": [{"host": "alpha"}, {"host": "beta"}]}
        assert get_by_dot(data, "servers.1.host") == "beta"

    def test_nested_lists(self) -> None:
        assert get_by_dot({"a": [[1, 2], [3]]}, "a.0.1") == 2

    def test_tuple_is_indexable_for_reads(self) -> None:
        assert get_by_dot({"a": ({"b": 1},)}, "a.0.b") == 1

    def test_leading_zero_index(self) -> None:
        """``"01"`` is all digits -> index 1."""
        assert get_by_dot({"a": [10, 20]}, "a.01") == 20

    def test_out_of_range_behaves_like_missing_key(self) -> None:
        with pytest.raises(KeyError) as exc:
            get_by_dot({"a": [1]}, "a.5")
        msg = str(exc.value)
        assert "a.5" in msg  # full requested path is reported
        assert "5" in msg  # the missing segment

    def test_out_of_range_mid_path_behaves_like_missing_key(self) -> None:
        with pytest.raises(KeyError):
            get_by_dot({"a": [{"b": 1}]}, "a.3.b")

    def test_non_ascii_digit_segment_is_not_an_index(self) -> None:
        """Only ASCII digits form indexes; unicode digits keep TypeError."""
        with pytest.raises(TypeError):
            get_by_dot({"a": [1, 2]}, "a.١")  # ARABIC-INDIC DIGIT ONE


# =============================================================================
# New: list-index traversal — set_by_dot
# =============================================================================


class TestSetByDotListIndexing:
    def test_assign_existing_index(self) -> None:
        d = {"a": [1, 2]}
        set_by_dot(d, "a.1", 99)
        assert d == {"a": [1, 99]}

    def test_assign_into_dict_inside_list(self) -> None:
        d = {"servers": [{"host": "a"}, {"host": "b"}]}
        set_by_dot(d, "servers.0.host", "changed")
        assert d == {"servers": [{"host": "changed"}, {"host": "b"}]}

    def test_assign_into_nested_lists(self) -> None:
        d = {"a": [[1, 2], [3]]}
        set_by_dot(d, "a.0.1", 22)
        assert d == {"a": [[1, 22], [3]]}

    def test_assign_existing_index_with_no_create(self) -> None:
        """create_missing=False still allows assigning to an EXISTING index."""
        d = {"a": [1, 2]}
        set_by_dot(d, "a.0", 7, create_missing=False)
        assert d == {"a": [7, 2]}

    def test_out_of_range_raises_and_never_grows(self) -> None:
        d = {"a": [1, 2]}
        with pytest.raises(KeyError) as exc:
            set_by_dot(d, "a.2", 5)
        assert "never grows lists" in str(exc.value)
        assert d == {"a": [1, 2]}  # untouched

    def test_out_of_range_raises_with_no_create_too(self) -> None:
        d = {"a": [1, 2]}
        with pytest.raises(KeyError):
            set_by_dot(d, "a.9", 5, create_missing=False)
        assert d == {"a": [1, 2]}

    def test_out_of_range_mid_path_raises(self) -> None:
        d = {"a": [{"b": 1}]}
        with pytest.raises(KeyError):
            set_by_dot(d, "a.4.b", 5)
        assert d == {"a": [{"b": 1}]}

    def test_scalar_element_replaced_by_dict_when_creating(self, caplog) -> None:
        """Deep-setting through an EXISTING index whose element is a scalar
        mirrors the dict behavior: warn and replace the element with a dict."""
        d = {"a": [1]}
        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            set_by_dot(d, "a.0.b", 7)
        assert d == {"a": [{"b": 7}]}

    def test_scalar_element_raises_when_not_creating(self) -> None:
        d = {"a": [1]}
        with pytest.raises(TypeError):
            set_by_dot(d, "a.0.b", 7, create_missing=False)
        assert d == {"a": [1]}

    def test_dict_value_wrapped_in_config_inside_config_tree(self) -> None:
        cfg = Config({"a": [{"x": 1}]})
        set_by_dot(cfg, "a.0", {"y": 2})
        assert isinstance(cfg["a"][0], Config)
        assert cfg.a[0].y == 2

    def test_dict_value_not_wrapped_in_plain_dict_tree(self) -> None:
        d = {"a": [{"x": 1}]}
        set_by_dot(d, "a.0", {"y": 2})
        assert not isinstance(d["a"][0], Config)
        assert d == {"a": [{"y": 2}]}


# =============================================================================
# New: list indexing through the Config class
# =============================================================================


class TestConfigListIndexing:
    def test_get_with_dot_key(self) -> None:
        cfg = Config({"servers": [{"host": "alpha"}, {"host": "beta"}]})
        assert cfg.get("servers.0.host") == "alpha"
        assert cfg.get("servers.1.host") == "beta"

    def test_get_default_on_out_of_range(self) -> None:
        cfg = Config({"servers": [{"host": "alpha"}]})
        assert cfg.get("servers.9.host", "fallback") == "fallback"

    def test_contains_with_dot_key(self) -> None:
        cfg = Config({"servers": [{"host": "alpha"}]})
        assert "servers.0.host" in cfg
        assert "servers.1.host" not in cfg
        assert "servers.0.port" not in cfg

    def test_list_elements_are_config_wrapped(self) -> None:
        """Config wraps dicts inside lists, so indexed traversal yields
        Config objects supporting further dot access."""
        cfg = Config({"servers": [{"host": "alpha"}]})
        assert isinstance(get_by_dot(cfg, "servers.0"), Config)

    def test_mandatory_validation_accepts_list_paths(self) -> None:
        """_validate_mandatory uses get_by_dot, so list paths now validate."""
        cfg = Config(
            defaults={"servers": [{"host": "alpha"}]},
            mandatory=["servers.0.host"],
            load_dotenv_file=False,
        )
        assert cfg.servers[0].host == "alpha"


# =============================================================================
# New: contains_dot
# =============================================================================


class TestContainsDot:
    def test_present_nested_key(self) -> None:
        assert contains_dot({"a": {"b": 1}}, "a.b") is True

    def test_missing_nested_key(self) -> None:
        assert contains_dot({"a": {"b": 1}}, "a.c") is False

    def test_missing_top_level_key(self) -> None:
        assert contains_dot({"a": 1}, "missing") is False

    def test_traversal_into_scalar_is_false_not_raise(self) -> None:
        assert contains_dot({"a": 1}, "a.b") is False

    def test_none_value_is_present(self) -> None:
        assert contains_dot({"a": None}, "a") is True

    def test_list_index_present(self) -> None:
        assert contains_dot({"a": [1, 2]}, "a.1") is True

    def test_list_index_out_of_range_is_false(self) -> None:
        assert contains_dot({"a": [1, 2]}, "a.5") is False

    def test_non_digit_segment_on_list_is_false_not_raise(self) -> None:
        assert contains_dot({"a": [1, 2]}, "a.b") is False

    def test_works_on_config(self) -> None:
        cfg = Config({"a": [{"b": 2}]})
        assert contains_dot(cfg, "a.0.b") is True
        assert contains_dot(cfg, "a.1.b") is False

    def test_never_mutates(self) -> None:
        d = {"a": {"b": 1}}
        contains_dot(d, "a.x.y")
        contains_dot(d, "a.b.c.d")
        assert d == {"a": {"b": 1}}

    def test_exported_from_package_root(self) -> None:
        import confy

        assert confy.contains_dot is contains_dot
        from confy import contains_dot as root_contains_dot

        assert root_contains_dot({"k": 1}, "k") is True
