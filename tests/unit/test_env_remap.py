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
