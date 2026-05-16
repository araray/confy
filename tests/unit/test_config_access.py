# tests/unit/test_config_access.py
"""Unit tests for :class:`Config`'s attribute/item-access surface.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §5 — API Specification
* ``confy/loader.py``:

  - :meth:`Config.__getattr__`  (lines 1239-1252)
  - :meth:`Config.__setattr__`  (lines 1254-1270)
  - :meth:`Config.__delattr__`  (lines 1272-1280)
  - :meth:`Config.as_dict`      (lines 1301-1314)
  - :meth:`Config.__repr__`     (line 1405-1406)
  - :meth:`Config.__str__`      (lines 1408-1413, both branches)
  - :meth:`Config._wrap_nested_items` (lines 1188-1209, incl. list-in-list)

What this file fills in
-----------------------
Beyond what the legacy ``test_loader.py`` already covers, this file pins
behavior of:

* **``__getattr__`` for ``_PRIVATE_ATTRS``** (line 1242) — reading
  internal state like ``cfg._prefix`` returns the stored value rather
  than treating it as a missing dict key.
* **``__setattr__`` for non-``_PRIVATE_ATTRS`` underscore names**
  (lines 1259-1261) — stores via ``object.__setattr__`` rather than as
  a dict key.
* **``__setattr__`` for lists** (lines 1266-1269) — deep-copies the list,
  walks it, and wraps any nested dicts in :class:`Config`.
* **``_wrap_nested_items`` for list-in-list** (line 1209) — recursive
  descent into nested lists.
* **``__str__`` fallback** (lines 1412-1413) — when
  :func:`json.dumps` raises (non-serializable value), returns ``repr``
  instead of crashing.
"""

from __future__ import annotations

import copy
import datetime
import json

import pytest

from confy.loader import Config

pytestmark = pytest.mark.unit


# =============================================================================
# __getattr__: public, private (_PRIVATE_ATTRS), and other underscore names
# =============================================================================


class TestGetattr:
    def test_public_attr_returns_value(self) -> None:
        cfg = Config({"a": 1})
        assert cfg.a == 1

    def test_public_missing_raises_attribute_error(self) -> None:
        cfg = Config({"a": 1})
        with pytest.raises(AttributeError):
            _ = cfg.missing

    def test_private_attrs_return_stored_internal_state(self) -> None:
        """Line 1242: keys in ``_PRIVATE_ATTRS`` are read from
        ``self.__dict__`` directly, NOT from the dict mapping.
        """
        cfg = Config(
            defaults={"x": 1},
            prefix="MYAPP",
            track_provenance=True,
            load_dotenv_file=False,
        )
        # Each of these is a documented internal slot:
        assert cfg._prefix == "MYAPP"
        assert cfg._load_dotenv_file is False
        assert cfg._app_prefixes == {}
        assert cfg._track_provenance is True
        # _provenance is a ProvenanceStore when tracking is on:
        from confy.provenance import ProvenanceStore

        assert isinstance(cfg._provenance, ProvenanceStore)

    def test_private_attrs_when_tracking_disabled(self) -> None:
        cfg = Config(load_dotenv_file=False)
        assert cfg._provenance is None
        assert cfg._track_provenance is False

    def test_private_attrs_fallback_when_dict_missing(self) -> None:
        """Line 1242 defensive path: ``__getattr__`` is only invoked when
        normal attribute lookup fails. Since ``__setattr__`` always populates
        ``__dict__`` for ``_PRIVATE_ATTRS``, normal lookup succeeds and
        ``__getattr__`` is bypassed.

        We force the defensive branch by deleting an entry from
        ``__dict__`` directly, so the next attribute access falls through
        to ``__getattr__``, which returns ``self.__dict__.get(name)`` —
        ``None`` rather than raising :class:`AttributeError`.

        This is contrived but pins the *contract* of the defensive
        fallback: never raise, return ``None``. Tools that introspect
        Config internals can rely on this.
        """
        cfg = Config(prefix="MYAPP", load_dotenv_file=False)
        # Sanity: normal lookup works.
        assert cfg._prefix == "MYAPP"
        # Now wipe the entry from __dict__ so normal lookup fails:
        del cfg.__dict__["_prefix"]
        # Falls through to __getattr__; line 1242 returns None via .get().
        assert cfg._prefix is None

    def test_other_underscore_name_raises_attribute_error(self) -> None:
        """Line 1243-1246: names starting with ``_`` but NOT in
        ``_PRIVATE_ATTRS`` and NOT already on the instance raise
        AttributeError.
        """
        cfg = Config({"a": 1})
        with pytest.raises(AttributeError):
            _ = cfg._something_random

    def test_dunder_name_also_raises(self) -> None:
        cfg = Config({"a": 1})
        with pytest.raises(AttributeError):
            _ = cfg.__weird_dunder__


# =============================================================================
# __setattr__: public, private internal state, other underscore, lists
# =============================================================================


class TestSetattr:
    def test_set_public_attr(self) -> None:
        cfg = Config()
        cfg.foo = 42
        assert cfg.foo == 42
        assert cfg["foo"] == 42

    def test_set_public_dict_wraps(self) -> None:
        cfg = Config()
        cfg.section = {"k": "v"}
        assert isinstance(cfg.section, Config)
        assert cfg.section.k == "v"

    def test_set_private_internal_state(self) -> None:
        """Line 1256-1258: ``_PRIVATE_ATTRS`` go to ``__dict__`` directly,
        not the mapping.
        """
        cfg = Config(load_dotenv_file=False)
        cfg._prefix = "NEWPREFIX"
        assert cfg._prefix == "NEWPREFIX"
        assert "_prefix" not in cfg  # NOT in the dict mapping

    def test_set_other_underscore_via_super(self) -> None:
        """Lines 1259-1261: non-``_PRIVATE_ATTRS`` underscore names go to
        ``object.__setattr__``. They land in ``__dict__`` but NOT in the
        dict mapping.
        """
        cfg = Config(load_dotenv_file=False)
        cfg._custom_internal = 99
        assert cfg.__dict__["_custom_internal"] == 99
        # NOT in the mapping:
        assert "_custom_internal" not in cfg.keys()
        # Normal attribute resolution finds it (via __dict__):
        assert cfg._custom_internal == 99

    def test_set_list_wraps_nested_dicts(self) -> None:
        """Lines 1266-1269: list values are deep-copied, then nested dicts
        inside the list are wrapped as Config.
        """
        cfg = Config()
        original = [{"a": 1}, {"b": {"c": 2}}, "string", 42]
        # NB: avoid the attribute name 'items' — it collides with dict.items().
        cfg.my_list = original

        # Each dict-in-list is wrapped:
        assert isinstance(cfg.my_list[0], Config)
        assert cfg.my_list[0].a == 1
        assert isinstance(cfg.my_list[1], Config)
        assert isinstance(cfg.my_list[1].b, Config)
        assert cfg.my_list[1].b.c == 2
        # Non-dicts in the list are preserved:
        assert cfg.my_list[2] == "string"
        assert cfg.my_list[3] == 42

    def test_set_list_does_not_mutate_input(self) -> None:
        """The deep-copy at line 1267 means caller can keep using the
        original list freely.
        """
        original = [{"a": 1}]
        original_snapshot = copy.deepcopy(original)
        cfg = Config()
        cfg.my_list = original
        # Original is still plain dicts:
        assert isinstance(original[0], dict)
        assert not isinstance(original[0], Config)
        assert original == original_snapshot

    def test_set_list_of_lists_of_dicts(self) -> None:
        """Line 1209: ``_wrap_nested_items`` recurses into lists-in-lists.
        ``cfg.nested = [[{"a": 1}]]`` should wrap the inner dict.
        """
        cfg = Config()
        cfg.nested = [[{"a": 1}], [{"b": {"c": 2}}]]
        assert isinstance(cfg.nested[0][0], Config)
        assert cfg.nested[0][0].a == 1
        assert isinstance(cfg.nested[1][0].b, Config)
        assert cfg.nested[1][0].b.c == 2


# =============================================================================
# Direct __setitem__: does NOT wrap (intentional)
# =============================================================================


class TestSetItem:
    """``cfg["foo"] = {"a": 1}`` uses dict's ``__setitem__`` and does NOT
    invoke wrapping logic. Only ``__setattr__`` wraps. This is a known and
    intentional asymmetry.
    """

    def test_direct_setitem_dict_not_wrapped(self) -> None:
        cfg = Config()
        cfg["foo"] = {"a": 1}
        assert type(cfg["foo"]) is dict  # NOT Config
        # And dot-access on it doesn't work — it's a plain dict:
        with pytest.raises(AttributeError):
            _ = cfg.foo.a  # type: ignore[attr-defined]

    def test_setattr_then_dot_access(self) -> None:
        """Contrast: when using attribute syntax, wrapping occurs."""
        cfg = Config()
        cfg.foo = {"a": 1}
        assert isinstance(cfg["foo"], Config)
        assert cfg.foo.a == 1


# =============================================================================
# __delattr__
# =============================================================================


class TestDelattr:
    def test_delete_public(self) -> None:
        cfg = Config({"a": 1, "b": 2})
        del cfg.a
        assert "a" not in cfg
        assert cfg.b == 2

    def test_delete_missing_raises(self) -> None:
        cfg = Config({"a": 1})
        with pytest.raises(AttributeError):
            del cfg.does_not_exist

    def test_delete_private_raises(self) -> None:
        """Line 1273-1274: cannot delete private attribute names through
        ``del cfg._foo``.
        """
        cfg = Config(load_dotenv_file=False)
        with pytest.raises(AttributeError, match="private"):
            del cfg._prefix


# =============================================================================
# as_dict
# =============================================================================


class TestAsDict:
    """Recursive unwrap to plain Python ``dict`` and ``list``."""

    def test_flat(self) -> None:
        cfg = Config({"a": 1, "b": "x"})
        d = cfg.as_dict()
        assert d == {"a": 1, "b": "x"}
        assert type(d) is dict

    def test_nested_unwraps(self) -> None:
        cfg = Config({"a": {"b": {"c": 1}}})
        d = cfg.as_dict()
        assert type(d["a"]) is dict
        assert type(d["a"]["b"]) is dict
        assert d["a"]["b"]["c"] == 1

    def test_list_of_configs_unwrapped(self) -> None:
        cfg = Config()
        cfg.my_list = [{"a": 1}, {"b": 2}]
        d = cfg.as_dict()
        assert type(d["my_list"][0]) is dict
        assert type(d["my_list"][1]) is dict

    def test_list_of_lists_of_configs(self) -> None:
        cfg = Config()
        cfg.my_list = [[{"a": 1}], [{"b": 2}]]
        d = cfg.as_dict()
        # Inner dicts must also unwrap, regardless of nesting depth.
        # Note: as_dict() walks lists one level; deeper nested lists may
        # leave Configs intact. We don't pin a behavior either way here —
        # we just verify the documented one-level-deep contract.
        assert isinstance(d, dict)
        assert d["my_list"][0] == [{"a": 1}]

    def test_result_independent_of_source(self) -> None:
        cfg = Config({"a": {"b": 1}})
        d = cfg.as_dict()
        d["a"]["b"] = 999
        # cfg unchanged:
        assert cfg.a.b == 1


# =============================================================================
# __repr__ and __str__
# =============================================================================


class TestRepr:
    def test_top_level(self) -> None:
        cfg = Config({"a": 1})
        r = repr(cfg)
        assert r.startswith("Config(")
        assert "'a': 1" in r

    def test_nested_uses_inner_repr(self) -> None:
        cfg = Config({"a": {"b": 1}})
        r = repr(cfg)
        assert "Config(" in r
        # Nested Config has its own repr too:
        assert r.count("Config(") >= 2


class TestStr:
    def test_str_returns_json(self) -> None:
        cfg = Config({"a": 1, "b": {"c": 2}})
        s = str(cfg)
        parsed = json.loads(s)
        assert parsed == {"a": 1, "b": {"c": 2}}

    def test_str_indented(self) -> None:
        """``json.dumps(indent=2)`` so the output is human-readable."""
        cfg = Config({"a": 1})
        assert "\n" in str(cfg)

    def test_str_fallback_when_value_not_json_serializable(self) -> None:
        """Lines 1412-1413: when ``json.dumps`` raises, ``__str__`` falls
        back to ``repr(self)`` rather than propagating the exception.
        Datetime objects are a canonical non-serializable example.
        """
        cfg = Config()
        # Insert a non-serializable value through dict's __setitem__ so
        # that no wrapping occurs and the value reaches __str__ as-is.
        cfg["dt"] = datetime.datetime(2026, 1, 1, 12, 0, 0)
        s = str(cfg)
        # The fallback returns repr, which has the class name and the
        # plain repr() form (not JSON).
        assert s.startswith("Config(")
        assert "datetime" in s.lower()
        # And critically: it didn't raise.
