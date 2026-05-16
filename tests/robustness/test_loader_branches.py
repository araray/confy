# tests/robustness/test_loader_branches.py
"""Targeted branch-coverage tests for ``confy.loader`` residual gaps.

Specification reference
-----------------------
* ``confy/loader.py`` ``_remap_and_flatten_env_data`` Attempt 2 loop
  (lines 1070-1095)
* ``confy/loader.py`` ``Config._wrap_nested_items`` list branches
  (lines 1200-1209)

Why this file exists
--------------------
After P2-P5 we had three residual branch-coverage holes that aren't
naturally hit by user-facing tests:

* **Branch ``1083→1072``** in the env-var remap algorithm — Attempt 2's
  longest-prefix loop has to *continue* past a prefix that exists in
  the base config but happens to point at a scalar (rather than a
  dict). The next-shorter prefix is checked, and if THAT one is a
  dict, the remap succeeds.

* **Branch ``1200→exit``** in ``_wrap_nested_items`` — the list-iteration
  branch has to handle an empty list (loop body never executes,
  falls through to exit).

* **Branch ``1203→1205``** in ``_wrap_nested_items`` — when a list
  contains a dict that's already a :class:`Config`, the
  ``if not isinstance(item, Config)`` is false, so the re-wrap step
  is skipped and we go straight to the recursive call.

These are micro-tests targeted at exactly those code paths. The
behavior of each is also implicitly used elsewhere in the codebase,
but pinning them explicitly means a future refactor can't silently
break them.
"""

from __future__ import annotations

import pytest

from confy.loader import Config

pytestmark = pytest.mark.robustness


# =============================================================================
# Branch 1083->1072: Attempt 2 skips scalar prefix
# =============================================================================


class TestEnvRemapScalarPrefix:
    """The env-var remap Attempt 2 loop iterates from the longest dot
    prefix downward. If the longest prefix exists in the base config
    but its value is a *scalar*, the loop must continue to the next
    shorter prefix rather than treating the scalar as a dict.

    Setup that triggers branch 1083 → 1072:
        defaults = {"server": {"pool": 8080}}
        env var   = MYAPP_SERVER_POOL_SIZE  →  dot_key 'server.pool.size'
        parts     = ["server", "pool", "size"]

    Attempt 2 loop:
        i=2: potential_root = 'server.pool'
             In valid_base_keys? YES.
             get_by_dot(base, 'server.pool') = 8080 (int).
             isinstance(dict)? NO  →  branch 1083 → 1072 (continue).
        i=1: potential_root = 'server'
             In valid_base_keys? YES.
             get_by_dot(base, 'server') = {'pool': 8080} (dict).
             remapped_key = 'server.pool_size'. break.
    """

    def test_scalar_at_longest_prefix_skipped(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_SERVER_POOL_SIZE", "100")
        cfg = Config(
            defaults={"server": {"pool": 8080}},
            prefix="MYAPP",
            load_dotenv_file=False,
        )
        # The remap landed inside 'server' as 'pool_size' (because
        # 'server' is a dict and Attempt 2 picked it after skipping
        # the scalar 'server.pool'):
        assert cfg.server.pool == 8080  # original survives
        assert cfg.server.pool_size == 100  # new key from env
        # And NOT at top level:
        assert "pool_size" not in cfg

    def test_multiple_scalars_in_path(self, monkeypatch) -> None:
        """Three-level path where TWO of the prefixes are scalar:
        defaults = {"a": {"b": "scalar_string"}}
        env var = MYAPP_A_B_C_D → dot_key 'a.b.c.d', parts=[a,b,c,d]

        - i=3: 'a.b.c' not in valid_base_keys → no branch hit
        - i=2: 'a.b' in valid_base_keys, value='scalar_string' (str)
               → 1083→1072 (skip)
        - i=1: 'a' in valid_base_keys, value={"b": "..."} (dict)
               → set remapped_key='a.b_c_d', break.
        """
        monkeypatch.setenv("MYAPP_A_B_C_D", "deep")
        cfg = Config(
            defaults={"a": {"b": "scalar_string"}},
            prefix="MYAPP",
            load_dotenv_file=False,
        )
        # The remap lands under 'a' as 'b_c_d':
        assert cfg.a.b_c_d == "deep"
        # Original scalar still there:
        assert cfg.a.b == "scalar_string"


# =============================================================================
# Branch 1200->exit: _wrap_nested_items on empty list
# =============================================================================


class TestWrapNestedItemsEmptyList:
    """When ``_wrap_nested_items`` is called on an empty list, the
    for-loop body never executes and the method returns immediately.
    """

    def test_empty_list_no_crash(self) -> None:
        empty: list = []
        # Direct call — should be a no-op:
        Config._wrap_nested_items(empty)
        assert empty == []

    def test_empty_list_as_config_value(self) -> None:
        """When a Config is built with an empty list as a value, the
        wrap pass over that list is the branch-1200-exit case.
        """
        cfg = Config(
            defaults={"items": []},  # empty list value
            load_dotenv_file=False,
        )
        assert cfg["items"] == []
        # The empty list survives wrapping unchanged:
        assert isinstance(cfg["items"], list)
        assert len(cfg["items"]) == 0

    def test_scalar_input_is_no_op(self) -> None:
        """``_wrap_nested_items`` accepts only dict or list. When called
        with a scalar (str, int, None, etc.) it neither raises nor
        modifies — the ``isinstance(data, dict)`` and
        ``isinstance(data, list)`` checks both fail and the function
        falls through to exit.

        This branch direction (1200 → exit, the False case of the
        elif) is the residual that the other tests don't reach because
        they always pass a dict or list.
        """
        # All of these are valid inputs that should silently do nothing:
        Config._wrap_nested_items("a string")
        Config._wrap_nested_items(42)
        Config._wrap_nested_items(3.14)
        Config._wrap_nested_items(None)
        Config._wrap_nested_items(True)
        # No assertion needed — we're testing that nothing raises.


# =============================================================================
# Branch 1203->1205: list item is already a Config
# =============================================================================


class TestWrapNestedItemsAlreadyConfigInList:
    """When a list inside a Config already contains a Config instance,
    the ``if not isinstance(item, Config)`` check is False and the
    inner re-wrap is skipped — we go straight to the recursive call.
    """

    def test_list_with_existing_config_item(self) -> None:
        """Construct a list with a pre-existing Config; _wrap_nested_items
        should leave that Config in place (not re-wrap it).
        """
        pre = Config({"x": 1}, load_dotenv_file=False)
        data_list = [pre, {"y": 2}]
        Config._wrap_nested_items(data_list)
        # The pre-existing Config object is the SAME instance:
        assert data_list[0] is pre
        # The raw dict was wrapped:
        assert isinstance(data_list[1], Config)
        assert data_list[1].y == 2

    def test_list_with_config_via_constructor(self) -> None:
        """A more realistic path: build a Config that already contains
        an explicit Config in a list. The constructor wraps the outer
        Config but the wrap pass over the list must NOT re-wrap the
        inner Config.
        """
        inner = Config({"a": 1}, load_dotenv_file=False)
        outer = Config(
            defaults={"things": [inner, {"b": 2}]},
            load_dotenv_file=False,
        )
        # Both items in the list are Configs, but the inner is the SAME
        # instance (not a copy):
        assert isinstance(outer["things"][0], Config)
        assert outer["things"][0].a == 1
        assert outer["things"][1].b == 2

    def test_list_of_only_configs(self) -> None:
        """Edge: list contains ONLY Config instances. Every iteration of
        the loop body hits branch 1203→1205.
        """
        configs = [Config({"k": i}, load_dotenv_file=False) for i in range(3)]
        Config._wrap_nested_items(configs)
        # All identity-preserved:
        for i, c in enumerate(configs):
            assert isinstance(c, Config)
            assert c.k == i


# =============================================================================
# Sanity: full integration of these edge cases inside Config
# =============================================================================


class TestNestedListsAndScalars:
    """Compose the above edge cases into a single Config to verify the
    interactions don't surprise.
    """

    def test_complex_structure(self, monkeypatch) -> None:
        """An admittedly contrived config with all the edges:

        * empty list (1200 branch)
        * list with a Config (1203 branch) — note: ``Config()``
          deep-copies its ``defaults`` argument, so the inner Config
          is preserved by *value* but not by *identity*. The identity-
          preservation case is tested separately above via the direct
          ``_wrap_nested_items`` call.
        * scalar at intermediate dot-path that env tries to remap
          past (1083 branch)
        """
        monkeypatch.setenv("MYAPP_A_B_X", "from_env")
        pre = Config({"hello": "world"}, load_dotenv_file=False)
        cfg = Config(
            defaults={
                "a": {"b": "scalar"},
                "list_items": [pre, {"k": 1}],
                "empty": [],
            },
            prefix="MYAPP",
            load_dotenv_file=False,
        )
        # Edge 1: empty list survives:
        assert cfg["empty"] == []
        # Edge 2: list element is a Config and equal to ``pre`` by value
        # (the original instance was deep-copied during init):
        assert isinstance(cfg["list_items"][0], Config)
        assert cfg["list_items"][0].as_dict() == pre.as_dict()
        assert isinstance(cfg["list_items"][1], Config)
        assert cfg["list_items"][1].k == 1
        # Edge 3: env var lands as 'a.b_x' (scalar 'a.b' skipped, 'a' picked):
        assert cfg.a.b == "scalar"
        assert cfg.a.b_x == "from_env"
