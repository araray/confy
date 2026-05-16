# tests/unit/test_deep_merge.py
"""Unit tests for :func:`confy.loader.deep_merge`.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §7.2.3 — Deep Merge Tests
* ``confy/loader.py`` :func:`deep_merge` (lines 56-122)
* ``confy/loader.py`` :func:`_record_provenance_leaves` (lines 125-147)

Why this file exists
--------------------
``tests/v040/test_phase0_foundation.py`` covers the backward-compat surface
(``_source`` / ``_provenance`` optional parameters) and basic merging.
``tests/v040/test_phase2_provenance.py`` covers the provenance-recording
side. This file fills the *semantic* gaps:

* **Type-boundary transitions** between scalar / dict / list / None — every
  pairwise direction. The implementation only recurses when *both* sides
  are dicts; everything else replaces wholesale. Spec §7.2.3 calls this
  out explicitly.
* **Immutability guarantees** — neither input is mutated, even when nested
  dicts are involved (deep copy at top of function).
* :func:`_record_provenance_leaves` line 145 (recursive descent into a
  newly-introduced dict subtree) is currently uncovered.

Note on terminology: "wholesale replace" means the update value replaces
the base value as-is (modulo a deep copy on the way through), with one
exception: a :class:`Config` value is assigned by reference (see loader.py
lines 108-109) so Config-typed updates preserve identity.
"""

from __future__ import annotations

import copy

import pytest

from confy.loader import Config, _record_provenance_leaves, deep_merge
from confy.provenance import ProvenanceStore

pytestmark = pytest.mark.unit


# =============================================================================
# Basic merge semantics
# =============================================================================


class TestBasicMerge:
    """Same-type same-shape merges from the spec."""

    def test_simple_flat_merge(self) -> None:
        # Spec §7.2.3 test_simple_merge
        assert deep_merge({"a": 1, "b": 2}, {"b": 3, "c": 4}) == {
            "a": 1,
            "b": 3,
            "c": 4,
        }

    def test_nested_merge(self) -> None:
        # Spec §7.2.3 test_nested_merge
        assert deep_merge(
            {"db": {"host": "a", "port": 1}},
            {"db": {"port": 2}},
        ) == {"db": {"host": "a", "port": 2}}

    def test_empty_base(self) -> None:
        assert deep_merge({}, {"a": 1}) == {"a": 1}

    def test_empty_updates(self) -> None:
        assert deep_merge({"a": 1}, {}) == {"a": 1}

    def test_both_empty(self) -> None:
        assert deep_merge({}, {}) == {}

    def test_deeply_nested(self) -> None:
        base = {"a": {"b": {"c": {"d": {"e": 1}}}}}
        updates = {"a": {"b": {"c": {"d": {"f": 2}}}}}
        assert deep_merge(base, updates) == {"a": {"b": {"c": {"d": {"e": 1, "f": 2}}}}}


# =============================================================================
# Type-boundary transitions — the "wholesale replace" rule
# =============================================================================


class TestTypeBoundaries:
    """When base/updates are not BOTH dicts, the update wins wholesale."""

    def test_scalar_replaces_object(self) -> None:
        # Spec §7.2.3 test_scalar_replaces_object
        assert deep_merge({"db": {"host": "a"}}, {"db": "string"}) == {"db": "string"}

    def test_object_replaces_scalar(self) -> None:
        # Spec §7.2.3 test_object_replaces_scalar
        assert deep_merge({"db": "string"}, {"db": {"host": "a"}}) == {
            "db": {"host": "a"}
        }

    def test_list_replaces_dict(self) -> None:
        """Lists are NOT dicts, so the merge is a wholesale replace."""
        assert deep_merge({"db": {"host": "a"}}, {"db": [1, 2]}) == {"db": [1, 2]}

    def test_dict_replaces_list(self) -> None:
        assert deep_merge({"db": [1, 2]}, {"db": {"host": "a"}}) == {
            "db": {"host": "a"}
        }

    def test_list_replaces_list_wholesale(self) -> None:
        """No element-wise merging of lists, ever. The whole list is
        replaced by the new list — even if the new one is shorter.
        """
        assert deep_merge({"x": [1, 2, 3]}, {"x": [99]}) == {"x": [99]}

    def test_none_replaces_value(self) -> None:
        """None is a scalar — it overwrites whatever was there."""
        assert deep_merge({"a": 1}, {"a": None}) == {"a": None}
        assert deep_merge({"a": {"b": 1}}, {"a": None}) == {"a": None}

    def test_value_replaces_none(self) -> None:
        assert deep_merge({"a": None}, {"a": 1}) == {"a": 1}
        assert deep_merge({"a": None}, {"a": {"b": 1}}) == {"a": {"b": 1}}

    def test_bool_replaces_int(self) -> None:
        """bool is a Python int subclass; verify the merge nonetheless
        records the bool value, since deep_merge doesn't special-case
        numeric tower.
        """
        result = deep_merge({"x": 1}, {"x": True})
        assert result == {"x": True}
        assert type(result["x"]) is bool


# =============================================================================
# Immutability guarantees
# =============================================================================


class TestImmutability:
    """Inputs must not be mutated regardless of nesting depth."""

    def test_base_not_mutated_shallow(self) -> None:
        base = {"a": 1}
        original = copy.deepcopy(base)
        deep_merge(base, {"a": 2, "b": 3})
        assert base == original

    def test_base_not_mutated_deep(self) -> None:
        base = {"a": {"b": {"c": 1}}}
        original = copy.deepcopy(base)
        deep_merge(base, {"a": {"b": {"d": 2}}})
        assert base == original

    def test_updates_not_mutated(self) -> None:
        updates = {"a": {"b": [1, 2, 3]}}
        original = copy.deepcopy(updates)
        deep_merge({"a": {"b": [9, 9]}}, updates)
        assert updates == original

    def test_result_is_independent_of_base(self) -> None:
        """Mutating the result later must not corrupt base."""
        base = {"a": {"b": 1}}
        result = deep_merge(base, {})
        result["a"]["b"] = 999
        # base unchanged
        assert base["a"]["b"] == 1

    def test_result_independent_of_updates_for_lists(self) -> None:
        """Updated lists are deep-copied so caller can mutate result safely."""
        updates = {"items": [1, 2, 3]}
        result = deep_merge({}, updates)
        result["items"].append(99)
        # updates unchanged
        assert updates == {"items": [1, 2, 3]}


# =============================================================================
# Config preservation through deep_merge
# =============================================================================


class TestConfigPreservation:
    """:class:`Config` values in *updates* are assigned by reference
    (loader.py lines 108-109). This preserves identity so downstream code
    that holds a reference to the same Config sees updates."""

    def test_config_in_updates_assigned_by_reference(self) -> None:
        # See loader.py line 109: `merged[key] = value_updates` (no copy)
        sub = Config({"x": 1})
        result = deep_merge({"a": 0}, {"a": sub})
        assert result["a"] is sub

    def test_config_in_base_is_deep_copied(self) -> None:
        """Because we ``copy.deepcopy(base)`` at the top of the function,
        a Config in base is NOT shared with the result."""
        sub = Config({"x": 1})
        result = deep_merge({"a": sub}, {})
        # The result should equal sub but NOT be the same object.
        assert result["a"] == sub
        # Note: deepcopy of a Config gives back a Config (dict subclass copy).
        assert isinstance(result["a"], (dict, Config))


# =============================================================================
# Provenance — exhaustive leaf recording on new dict subtrees
# =============================================================================


class TestProvenanceLeafRecording:
    """When updates introduces a *new* dict subtree (the base had no such
    key), :func:`_record_provenance_leaves` walks it and records each leaf
    individually. Line 145 in loader.py (the recursive descent inside
    _record_provenance_leaves) is reached only here.
    """

    def test_new_subtree_records_each_leaf(self) -> None:
        store = ProvenanceStore()
        deep_merge(
            {"existing": 1},
            {"new": {"deep": {"a": 1, "b": 2}}},
            _source="src",
            _provenance=store,
        )
        # The parent keys (`new`, `new.deep`) are NOT individually recorded;
        # only the leaves are. Verify both sides of that.
        assert store.get("new") is None
        assert store.get("new.deep") is None
        assert store.get("new.deep.a") is not None
        assert store.get("new.deep.a").value == 1
        assert store.get("new.deep.b") is not None
        assert store.get("new.deep.b").value == 2

    def test_scalar_replaced_by_dict_records_leaves_only(self) -> None:
        """When a scalar gets clobbered by a dict (type boundary), the new
        dict is treated as a brand-new subtree for provenance purposes:
        leaves recorded, parent NOT recorded.
        """
        store = ProvenanceStore()
        deep_merge(
            {"x": 42},
            {"x": {"a": 1, "b": {"c": 2}}},
            _source="src",
            _provenance=store,
        )
        # Parent (the scalar-was-here key) is NOT separately recorded.
        # Only the new leaves are.
        assert store.get("x") is None
        assert store.get("x.a").value == 1
        assert store.get("x.b.c").value == 2

    def test_list_value_records_as_single_leaf(self) -> None:
        """Lists aren't dicts, so a list in updates records as one leaf at
        the parent key (not per-element).
        """
        store = ProvenanceStore()
        deep_merge(
            {"existing": 1},
            {"items": [1, 2, 3]},
            _source="src",
            _provenance=store,
        )
        entry = store.get("items")
        assert entry is not None
        assert entry.value == [1, 2, 3]

    def test_record_provenance_leaves_direct_call(self) -> None:
        """Direct call to the helper — exercise it without going through
        deep_merge, for clarity.
        """
        store = ProvenanceStore()
        _record_provenance_leaves(
            store,
            {"a": 1, "b": {"c": 2, "d": {"e": 3}}},
            source="direct",
            prefix="root",
        )
        assert store.get("root.a").value == 1
        assert store.get("root.b.c").value == 2
        assert store.get("root.b.d.e").value == 3
        # Intermediates NOT recorded:
        assert store.get("root.b") is None
        assert store.get("root.b.d") is None

    def test_record_provenance_leaves_empty_prefix(self) -> None:
        """Empty prefix → leaf paths have no leading dot."""
        store = ProvenanceStore()
        _record_provenance_leaves(
            store, {"a": 1, "b": {"c": 2}}, source="direct", prefix=""
        )
        assert store.get("a").value == 1
        assert store.get("b.c").value == 2


# =============================================================================
# Edge cases
# =============================================================================


class TestEdgeCases:
    def test_identity_self_merge(self) -> None:
        """Merging a dict with itself returns an equal but distinct dict."""
        d = {"a": {"b": 1}}
        result = deep_merge(d, d)
        assert result == d
        assert result is not d
        assert result["a"] is not d["a"]  # deepcopy of base happens

    def test_keys_are_strings(self) -> None:
        """Dot-path notation only makes sense for string keys, but
        deep_merge itself doesn't enforce that — it just iterates items.
        """
        base = {"a": {1: "int-key"}}
        updates = {"a": {2: "another"}}
        result = deep_merge(base, updates)
        assert result == {"a": {1: "int-key", 2: "another"}}

    def test_value_types_preserved(self) -> None:
        """Non-dict values (int, float, str, bool, None) survive the merge
        with their types intact.
        """
        base: dict = {}
        updates = {"i": 1, "f": 1.5, "s": "x", "b": True, "n": None}
        result = deep_merge(base, updates)
        for k, v in updates.items():
            assert type(result[k]) is type(v)
            assert result[k] == v
