# tests/unit/test_env_remap.py
"""Unit tests for env-var remapping and override structuring.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §3.3, §7.2.4
* ``confy/loader.py``:

  - :meth:`Config._remap_and_flatten_env_data` (lines 972-1138)
  - :meth:`Config._flatten_keys`                (lines 1140-1154)
  - :meth:`Config._structure_overrides`         (lines 1156-1186)

What these functions do
-----------------------
After :meth:`Config._collect_env_vars` produces a *nested* dict from env
vars, :meth:`Config._remap_and_flatten_env_data` walks that dict and tries
to match each leaf path to a key that already exists in defaults/file
data. Three attempts are made:

* **Heuristic 0** (lines 1029-1059): rebuild the leaf path with underscores
  and try splitting on the *first* underscore as the boundary between a
  base key and the rest.
* **Attempt 1** (lines 1061-1067): exact match of the underscore-joined
  reconstructed key against any valid base key.
* **Attempt 2** (lines 1069-1094): scan from the longest dot-prefix down
  and stop at the first prefix that maps to a *dict* in the base config.

If nothing matches, three fallbacks apply:

* prefix == ``""``           → preserve dot-form key as-is.
* prefix set + dotenv loaded → preserve dot-form key as-is.
* prefix set + direct env    → flatten back to underscore key.

A **conflict** (two env vars resolving to the same target) is logged as a
warning and the deeper / earlier mapping wins (line 1130-1133).

Known bug
---------
Heuristic 0 splits the reconstructed key on the *first* underscore only,
which fails when both the base key and the env-var suffix contain
underscores (e.g. ``feature_flags`` + ``new_ui``). This is documented and
xfail-quarantined via four tests in ``tests/test_loader.py`` — see the
``_KNOWN_ENV_REMAP_BUG`` constant there. This file does **not** add new
xfails for the same bug; it tests only what currently works.
"""

from __future__ import annotations

import logging

import pytest

from confy.loader import Config

pytestmark = pytest.mark.unit


# =============================================================================
# _flatten_keys
# =============================================================================


class TestFlattenKeys:
    """Produces a flat list of every dot-notation path in a dict/Config."""

    def test_flat_dict(self) -> None:
        assert Config._flatten_keys({"a": 1, "b": 2}) == ["a", "b"]

    def test_nested(self) -> None:
        keys = Config._flatten_keys({"a": {"b": {"c": 1}}})
        # All intermediate paths included, not just leaves.
        assert "a" in keys
        assert "a.b" in keys
        assert "a.b.c" in keys

    def test_with_config_objects(self) -> None:
        cfg = Config({"a": Config({"b": 1})})
        keys = Config._flatten_keys(cfg)
        assert "a" in keys and "a.b" in keys

    def test_prefix_arg(self) -> None:
        keys = Config._flatten_keys({"a": 1}, prefix="root")
        assert keys == ["root.a"]

    def test_empty(self) -> None:
        assert Config._flatten_keys({}) == []


# =============================================================================
# _remap_and_flatten_env_data: matching paths
# =============================================================================


class TestRemapDirectMatch:
    """Attempt 1 — the underscore-joined reconstructed key matches a base key
    verbatim.
    """

    def test_two_segment_match(self) -> None:
        """env ``DATABASE.HOST`` against base ``database.host`` (dict)."""
        nested_env = {"database": {"host": "h"}}
        base_defaults = {"database": {"host": "default"}}
        result = Config._remap_and_flatten_env_data(
            nested_env, base_defaults, {}, "MYAPP", False
        )
        assert result == {"database.host": "h"}

    def test_underscore_base_key_exact_match(self) -> None:
        """env var maps to ``feature.flags`` which underscored is
        ``feature_flags`` — matches a known top-level base key with an
        underscore in it. Attempt 1 success.
        """
        nested_env = {"feature": {"flags": "v"}}
        base_defaults = {"feature_flags": "default"}
        result = Config._remap_and_flatten_env_data(
            nested_env, base_defaults, {}, "MYAPP", False
        )
        assert result == {"feature_flags": "v"}


class TestRemapAttempt2:
    """Attempt 2 — longest dot-prefix match against a dict in base config.

    Lines 1069-1094 are reached only here.
    """

    def test_secrets_api_key_pattern(self) -> None:
        """env ``MYAPP_SECRETS_API_KEY`` → nested ``secrets.api.key``.
        Base has ``secrets`` as a dict. Attempt 2 falls back to
        prefix=``secrets`` (longest matching dict) and joins the rest with
        underscores: ``secrets.api_key``.
        """
        nested_env = {"secrets": {"api": {"key": "v"}}}
        base_defaults = {"secrets": {"some_other": "x"}}
        result = Config._remap_and_flatten_env_data(
            nested_env, base_defaults, {}, "MYAPP", False
        )
        assert result == {"secrets.api_key": "v"}

    def test_attempt2_with_three_extra_segments(self) -> None:
        """``MYAPP_DB_CONN_POOL_SIZE`` → ``db.conn.pool.size``;
        base has ``db`` as a dict → ``db.conn_pool_size``.

        Note: :meth:`_remap_and_flatten_env_data` does NOT call
        :func:`_parse_value` — value parsing happens earlier inside
        :meth:`_collect_env_vars`. When we construct ``nested_env``
        manually, the value stays as whatever we put in.
        """
        nested_env = {"db": {"conn": {"pool": {"size": "10"}}}}
        base_defaults = {"db": {"host": "x"}}
        result = Config._remap_and_flatten_env_data(
            nested_env, base_defaults, {}, "MYAPP", False
        )
        assert result == {"db.conn_pool_size": "10"}

    def test_attempt2_prefers_file_over_defaults(self) -> None:
        """When defaults and file disagree, the merged base view is used.
        The file's structure participates in remapping decisions.
        """
        nested_env = {"db": {"x": "v"}}
        result = Config._remap_and_flatten_env_data(
            nested_env,
            defaults_data={},  # No defaults at all
            file_data={"db": {"some": "thing"}},  # File defines db
            prefix="MYAPP",
            load_dotenv_file=False,
        )
        # `db` is a dict in the merged base (from file), so attempt 2 works.
        assert result == {"db.x": "v"}


# =============================================================================
# Fallback branches when nothing matches
# =============================================================================


class TestRemapFallbacks:
    """When no remap target is found, three fallback rules apply."""

    def test_fallback_empty_prefix_uses_dot_form(self) -> None:
        """prefix="" → preserve dot-form key (line 1103-1108)."""
        nested_env = {"unknown": {"key": "v"}}
        result = Config._remap_and_flatten_env_data(
            nested_env, {}, {}, prefix="", load_dotenv_file=False
        )
        assert result == {"unknown.key": "v"}

    def test_fallback_dotenv_uses_dot_form(self) -> None:
        """prefix set + load_dotenv_file=True → preserve dot-form key
        (line 1111-1116)."""
        nested_env = {"unknown": {"key": "v"}}
        result = Config._remap_and_flatten_env_data(
            nested_env, {}, {}, prefix="MYAPP", load_dotenv_file=True
        )
        assert result == {"unknown.key": "v"}

    def test_fallback_direct_env_flattens_to_underscore(self) -> None:
        """prefix set + load_dotenv_file=False → flatten back to
        underscore key (line 1117-1120). This is what makes
        ``ADDED_BY_ENV`` show up as ``added_by_env`` instead of nesting.
        """
        nested_env = {"added": {"by": {"env": "v"}}}
        result = Config._remap_and_flatten_env_data(
            nested_env, {}, {}, prefix="MYAPP", load_dotenv_file=False
        )
        assert result == {"added_by_env": "v"}

    def test_fallback_with_partial_match(self) -> None:
        """When some keys match and others don't, the fallback applies
        only to the non-matching ones.
        """
        nested_env = {
            "database": {"host": "matched"},
            "unknown": {"x": "fallback"},
        }
        base = {"database": {"host": "default"}}
        result = Config._remap_and_flatten_env_data(
            nested_env, base, {}, "MYAPP", False
        )
        assert result["database.host"] == "matched"
        # Direct-env fallback for the unmatched branch:
        assert result["unknown_x"] == "fallback"


# =============================================================================
# Conflict handling (line 1130-1133)
# =============================================================================


class TestRemapConflicts:
    """When two env vars produce the same remapped target, the deeper/earlier
    mapping wins and a warning is logged.
    """

    def test_conflict_first_wins(self, caplog) -> None:
        """The iteration is sorted by depth descending, so the deeper-key
        source resolves first and wins the slot; the second mapping is
        skipped with a warning.
        """
        # Both could plausibly remap to ``a.b``:
        # - ``nested["a"]["b"]`` directly has dot_key "a.b" (1 dot).
        # - ``nested["a_b"]`` has dot_key "a_b" (0 dots) → via heuristic 0
        #   it splits as a + b → candidate "a.b" → matches base ``a.b``.
        nested_env = {"a": {"b": "first"}, "a_b": "second"}
        base = {"a": {"b": "x"}}
        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            result = Config._remap_and_flatten_env_data(
                nested_env, base, {}, "MYAPP", False
            )
        # The deeper (a.b dot-form, 1 dot) is processed first and wins.
        assert result["a.b"] == "first"
        # The skipped value is NOT silently merged; it's dropped + logged.
        # Heuristic-0 path: log message contains "(heuristic)".
        assert any(
            "(heuristic)" in r.message and "Skipping" in r.message
            for r in caplog.records
        )

    def test_conflict_in_fallback_branch(self, caplog) -> None:
        """A different conflict pathway: with NO base config, both keys
        fall through to the direct-env flattening fallback (line 1120),
        which produces the same final_key. The second one hits the
        final-assignment conflict check at line 1131 (distinct from the
        heuristic-0 conflict at line 1056).

        - ``nested["a"]["b"]``: dot_key ``a.b`` → no base match → fallback
          flatten → ``a_b``.
        - ``nested["a_b"]``  : dot_key ``a_b`` → no base match (heuristic 0
          finds no candidate either) → fallback (direct-env) → ``a_b``.
        - Iteration is sorted by dot-count descending, so ``a.b`` (1 dot)
          is added first; ``a_b`` (0 dots) hits the conflict.

        The warning message *lacks* the ``(heuristic)`` token, which
        distinguishes it from the line-1056 case.
        """
        nested_env = {"a": {"b": "first"}, "a_b": "second"}
        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            result = Config._remap_and_flatten_env_data(
                nested_env, {}, {}, "MYAPP", False
            )
        assert result == {"a_b": "first"}
        # Final-key-conflict warning: NO "(heuristic)" token.
        final_conflict_warnings = [
            r
            for r in caplog.records
            if "Skipping" in r.message and "(heuristic)" not in r.message
        ]
        assert len(final_conflict_warnings) == 1


# =============================================================================
# Edge cases
# =============================================================================


class TestRemapEdgeCases:
    def test_empty_nested_data(self) -> None:
        result = Config._remap_and_flatten_env_data(
            {}, {"db": {"host": "x"}}, {}, "MYAPP", False
        )
        assert result == {}

    def test_empty_base(self) -> None:
        """With no base config and no remap targets, fall back per the
        prefix/dotenv rules."""
        nested_env = {"a": {"b": "v"}}
        result = Config._remap_and_flatten_env_data(nested_env, {}, {}, "MYAPP", False)
        # Direct-env fallback: flattened underscore.
        assert result == {"a_b": "v"}

    def test_single_segment_dot_key(self) -> None:
        """A top-level scalar env var (no nesting in nested_env)."""
        nested_env = {"flag": "true"}
        result = Config._remap_and_flatten_env_data(nested_env, {}, {}, "", False)
        # No dots, no underscores in 'flag' — both fallbacks coincide.
        assert result == {"flag": "true"}


# =============================================================================
# _structure_overrides
# =============================================================================


class TestStructureOverrides:
    """Inverse of flattening — takes a flat ``{"a.b": value}`` and produces
    ``{"a": {"b": value}}``.
    """

    def test_simple(self) -> None:
        result = Config._structure_overrides({"a.b": 1})
        assert result == {"a": {"b": 1}}

    def test_multiple_keys(self) -> None:
        result = Config._structure_overrides({"a.b": 1, "a.c": 2, "x": 3})
        assert result == {"a": {"b": 1, "c": 2}, "x": 3}

    def test_deeply_nested(self) -> None:
        result = Config._structure_overrides({"a.b.c.d.e": 42})
        assert result == {"a": {"b": {"c": {"d": {"e": 42}}}}}

    def test_value_parsing(self) -> None:
        """String values pass through ``_parse_value``."""
        result = Config._structure_overrides({"a.flag": "true", "a.num": "42"})
        assert result == {"a": {"flag": True, "num": 42}}

    def test_none_returns_empty(self) -> None:
        assert Config._structure_overrides(None) == {}

    def test_empty_dict(self) -> None:
        assert Config._structure_overrides({}) == {}

    def test_non_string_keys_raise_at_sort(self) -> None:
        """Pinned behavior: a non-string key in ``overrides_dict`` is not
        handled gracefully by :meth:`_structure_overrides`. The function
        calls :func:`sorted` on the keys (line 1170) before the per-key
        try/except, so the comparison ``int < str`` raises :class:`TypeError`
        at the top level.

        This means the broad ``except Exception`` clause at lines
        1182-1183 — designed to catch per-key processing errors — is
        currently unreachable through this entry point for the most likely
        failure mode (non-string keys). With all-string keys,
        :func:`set_by_dot` with ``create_missing=True`` doesn't raise.

        The defensive clause therefore remains uncovered. If we ever
        decide to make non-string keys a soft failure, the sort would
        need to be replaced with a stable iteration that doesn't compare
        keys.
        """
        with pytest.raises(TypeError):
            Config._structure_overrides({42: "bogus", "valid.key": "ok"})

    def test_result_is_independent_of_input(self) -> None:
        """The function deep-copies before returning (line 1186), so
        mutations on the result don't affect anything.
        """
        inp = {"a.b": [1, 2, 3]}
        result = Config._structure_overrides(inp)
        result["a"]["b"].append(99)
        assert inp == {"a.b": [1, 2, 3]}


# =============================================================================
# Heuristic 0 — longest underscore-prefix match (I-01 fix)
# =============================================================================


class TestHeuristic0LongestPrefix:
    """Heuristic 0 (post-I-01) iterates over EVERY underscore position in
    the reconstructed flat key, from the longest possible prefix to the
    shortest, and uses the first prefix that resolves to a *dict* in the
    base config.

    Before the fix it split on the FIRST underscore only, which failed
    whenever an env-var path had >2 segments AND the base key contained
    an underscore (e.g. ``feature_flags`` + ``beta_feature``). These
    tests pin the corrected behavior.
    """

    def test_feature_flags_beta_feature_four_segments(self) -> None:
        """The canonical bug case from the inventory: ``feature_flags``
        is a dict in defaults and the env path is four segments deep.
        Pre-fix this fell back to a flat ``feature_flags_beta_feature``
        top-level key; post-fix it must nest correctly.
        """
        nested_env = {"feature": {"flags": {"beta": {"feature": True}}}}
        base_defaults = {"feature_flags": {"beta_feature": False}}
        result = Config._remap_and_flatten_env_data(
            nested_env, base_defaults, {}, "MYAPP", False
        )
        assert result == {"feature_flags.beta_feature": True}

    def test_db_pool_max_size(self) -> None:
        """``MYAPP_DB_POOL_MAX_SIZE`` → ``db_pool.max_size`` when
        ``db_pool`` is a dict containing ``max_size`` in defaults.
        """
        nested_env = {"db": {"pool": {"max": {"size": 100}}}}
        base_defaults = {"db_pool": {"max_size": 10}}
        result = Config._remap_and_flatten_env_data(
            nested_env, base_defaults, {}, "MYAPP", False
        )
        assert result == {"db_pool.max_size": 100}

    def test_my_section_two_segments(self) -> None:
        """The 2-segment case the OLD heuristic 0 also handled: a single
        underscore in the base key.
        """
        nested_env = {"my": {"section": "val"}}
        base_defaults = {"my_section": "x"}
        result = Config._remap_and_flatten_env_data(
            nested_env, base_defaults, {}, "MYAPP", False
        )
        # Heuristic 0 finds "my_section" via the underscore-split path
        # AND Attempt 1 also matches it directly; either way the result
        # is the same.
        assert result == {"my_section": "val"}

    def test_longest_prefix_wins(self) -> None:
        """When several underscore-prefixes of the reconstructed flat
        key match valid base dict-keys, the LONGEST one wins (most
        specific match).
        """
        nested_env = {"a": {"b": {"c": "v"}}}
        # Both ``a`` and ``a_b`` are dicts in base; longest match
        # (``a_b``) should be chosen.
        base_defaults = {
            "a_b": {"c": "x"},
            "a": {"b_c": "y"},  # also a plausible match, but shorter prefix
        }
        result = Config._remap_and_flatten_env_data(
            nested_env, base_defaults, {}, "MYAPP", False
        )
        assert result == {"a_b.c": "v"}

    def test_prefix_must_be_dict_not_scalar(self) -> None:
        """If the matching prefix points to a *scalar* (not a dict) in
        base, the heuristic skips it and falls through to the next
        candidate / fallback.
        """
        nested_env = {"a": {"b": "v"}}
        base_defaults = {"a": "leaf_string"}  # ``a`` is a scalar, not dict
        result = Config._remap_and_flatten_env_data(
            nested_env, base_defaults, {}, "MYAPP", False
        )
        # No remap; falls back to flat (load_dotenv_file=False, prefix set).
        assert result == {"a_b": "v"}

    def test_three_segment_underscore_base_at_root(self) -> None:
        """``MYAPP_FOO_BAR_BAZ`` with ``foo_bar`` (dict) and a sub-key
        ``baz`` (leaf) in defaults → ``foo_bar.baz``.
        """
        nested_env = {"foo": {"bar": {"baz": 42}}}
        base_defaults = {"foo_bar": {"baz": 0}}
        result = Config._remap_and_flatten_env_data(
            nested_env, base_defaults, {}, "MYAPP", False
        )
        assert result == {"foo_bar.baz": 42}


# =============================================================================
# I-05 — env_remap_fallback parameter
# =============================================================================


class TestEnvRemapFallback:
    """The new ``env_remap_fallback`` parameter (I-05 fix) decouples the
    fallback strategy from ``load_dotenv_file``. Three modes:

    * ``"auto"``  — historical behavior: empty-prefix or dotenv mode →
      nested; otherwise → flat. Default for backward compatibility.
    * ``"nested"`` — always preserve dot form regardless of mode.
    * ``"flat"``   — always collapse to underscore form regardless of
      mode. Best for callers (like the argparse helper) that want a
      deterministic shape.

    These tests exercise the static :meth:`_remap_and_flatten_env_data`
    directly; the higher-level :class:`Config` constructor merely
    forwards the parameter.
    """

    def test_auto_dotenv_mode_is_nested_when_prefix_set(self) -> None:
        nested_env = {"unknown": {"key": "v"}}
        result = Config._remap_and_flatten_env_data(
            nested_env, {}, {}, "MYAPP", True, "auto"
        )
        assert result == {"unknown.key": "v"}

    def test_auto_no_dotenv_mode_is_flat_when_prefix_set(self) -> None:
        nested_env = {"unknown": {"key": "v"}}
        result = Config._remap_and_flatten_env_data(
            nested_env, {}, {}, "MYAPP", False, "auto"
        )
        assert result == {"unknown_key": "v"}

    def test_explicit_flat_overrides_dotenv_mode(self) -> None:
        """The user can force flat fallback even with .env mode on."""
        nested_env = {"unknown": {"key": "v"}}
        result = Config._remap_and_flatten_env_data(
            nested_env, {}, {}, "MYAPP", True, "flat"
        )
        # Without I-05 fix this would have been ``{"unknown.key": "v"}``:
        assert result == {"unknown_key": "v"}

    def test_explicit_nested_overrides_direct_env_mode(self) -> None:
        """Mirror image: force nested fallback even without .env mode."""
        nested_env = {"unknown": {"key": "v"}}
        result = Config._remap_and_flatten_env_data(
            nested_env, {}, {}, "MYAPP", False, "nested"
        )
        # Without I-05 fix this would have been ``{"unknown_key": "v"}``:
        assert result == {"unknown.key": "v"}

    def test_default_value_is_auto(self) -> None:
        """When the param is omitted, behavior matches ``"auto"``."""
        nested_env = {"unknown": {"key": "v"}}
        with_default = Config._remap_and_flatten_env_data(
            nested_env, {}, {}, "MYAPP", False
        )
        explicit_auto = Config._remap_and_flatten_env_data(
            nested_env, {}, {}, "MYAPP", False, "auto"
        )
        assert with_default == explicit_auto

    def test_empty_prefix_always_nested_under_auto(self) -> None:
        """Empty-prefix special case under ``"auto"`` ignores
        ``load_dotenv_file`` and always nests.
        """
        nested_env = {"unknown": {"key": "v"}}
        result_t = Config._remap_and_flatten_env_data(
            nested_env, {}, {}, "", True, "auto"
        )
        result_f = Config._remap_and_flatten_env_data(
            nested_env, {}, {}, "", False, "auto"
        )
        assert result_t == result_f == {"unknown.key": "v"}

    def test_config_constructor_validates_fallback_string(self) -> None:
        """An invalid fallback string is rejected up-front with a clear
        :class:`ValueError`.
        """
        with pytest.raises(ValueError, match="env_remap_fallback"):
            Config(env_remap_fallback="bogus_mode")  # type: ignore[arg-type]
