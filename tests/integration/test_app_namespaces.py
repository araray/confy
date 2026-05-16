# tests/integration/test_app_namespaces.py
"""Integration tests for app-namespaced configuration features.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §5 (Config API)
* ``confy/loader.py`` ``__init__`` lines 591-623 (app_prefixes routing)
* ``confy/loader.py`` :meth:`Config.app` lines 1317-1351

What this file fills in beyond ``tests/v040/test_phase1_multifile.py``
---------------------------------------------------------------------
* **Line 594 → 592 branch**: ``app_prefixes`` provided but the
  corresponding env vars are NOT set — the inner ``if app_env_data:``
  is false, so the body is skipped and the loop moves on.
* **Lines 1348-1350**: ``Config.app(name)`` finds a *raw* dict at
  ``self[name]`` (i.e., not yet wrapped) and wraps it into a Config
  in place. This branch isn't reachable through normal Config init
  (which wraps everything) — it requires post-construction
  manipulation via ``dict.__setitem__`` (or future code that doesn't
  use ``__setattr__``).
* **Cross-app isolation**: app prefixes don't bleed between
  namespaces.
* **Full chain**: ``app_defaults`` → namespaced file → ``app_prefixes``
  env vars → ``overrides_dict`` keys nested in the app namespace.
"""

from __future__ import annotations

import json

import pytest

from confy.loader import Config

pytestmark = pytest.mark.integration


# =============================================================================
# Config.app() — the raw-dict wrap branch (lines 1348-1350)
# =============================================================================


class TestAppRawDictWrap:
    """``Config.app(name)`` must handle the case where ``self[name]`` is a
    *raw* ``dict`` (not yet a Config) — it wraps in place.
    """

    def test_raw_dict_inserted_post_construction_gets_wrapped(self) -> None:
        """The trick: ``dict.__setitem__`` bypasses ``Config.__setattr__``
        and stores a raw dict. Then ``cfg.app(...)`` is the first thing
        to see this raw dict and must wrap it.
        """
        cfg = Config(load_dotenv_file=False)
        dict.__setitem__(cfg, "myapp", {"key": "val", "nested": {"k": "v"}})
        # Confirm setup: raw dict at this point.
        assert type(cfg["myapp"]) is dict

        # Call app() — this hits the line 1346-1350 branch.
        sub = cfg.app("myapp")

        # Returns a Config:
        assert isinstance(sub, Config)
        assert sub.key == "val"
        # And cfg["myapp"] is now also a Config (wrapped in place):
        assert isinstance(cfg["myapp"], Config)

    def test_wrapped_dict_chained_dot_access(self) -> None:
        """After wrapping via app(), nested dot-notation works."""
        cfg = Config(load_dotenv_file=False)
        dict.__setitem__(cfg, "myapp", {"deep": {"down": "found"}})
        sub = cfg.app("myapp")
        # The wrap recursively wraps nested dicts:
        assert isinstance(sub.deep, (dict, Config))
        # And dot access through nested levels works:
        assert sub.deep.down == "found"

    def test_already_wrapped_returns_same_instance(self) -> None:
        """If ``cfg[name]`` is *already* a Config (the normal case after
        construction), app() returns it without re-wrapping.
        """
        cfg = Config(
            app_defaults={"myapp": {"k": "v"}},
            load_dotenv_file=False,
        )
        first = cfg.app("myapp")
        second = cfg.app("myapp")
        assert first is second


# =============================================================================
# app_prefixes routing — branch coverage
# =============================================================================


class TestAppPrefixRouting:
    """``app_prefixes={"myapp": "MYAPP"}`` routes ``MYAPP_*`` env vars
    under the ``myapp`` namespace in the merged config.
    """

    def test_env_var_routed_to_namespace(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_KEY", "from_env")
        cfg = Config(
            app_defaults={"myapp": {"key": "default", "other": "x"}},
            app_prefixes={"myapp": "MYAPP"},
            load_dotenv_file=False,
        )
        assert cfg.myapp.key == "from_env"
        assert cfg.myapp.other == "x"  # not in env — preserved

    def test_no_env_vars_set_skips_body(self, monkeypatch) -> None:
        """Line 594 → 592 branch: ``app_prefixes`` is provided but no
        ``MYAPP_*`` env vars are set, so ``_collect_env_vars`` returns
        an empty dict; the conditional body is skipped and we loop on.
        """
        # Ensure absolutely no matching env vars exist:
        for k in list(monkeypatch.delenv) if False else []:
            pass  # no-op; the autouse _env_snapshot already cleans up
        # Build with app_prefixes but nothing to route:
        cfg = Config(
            app_defaults={"myapp": {"k": "default"}},
            app_prefixes={"myapp": "NONEXISTENT_PREFIX_FOR_TEST_ZZZ"},
            load_dotenv_file=False,
        )
        # The body was skipped; defaults remain:
        assert cfg.myapp.k == "default"

    def test_multiple_app_prefixes_isolated(self, monkeypatch) -> None:
        """Each app prefix routes only to its own namespace."""
        monkeypatch.setenv("APP_A_KEY", "from_a")
        monkeypatch.setenv("APP_B_KEY", "from_b")
        cfg = Config(
            app_defaults={
                "alpha": {"key": "default_a", "only_a": 1},
                "beta": {"key": "default_b", "only_b": 2},
            },
            app_prefixes={"alpha": "APP_A", "beta": "APP_B"},
            load_dotenv_file=False,
        )
        assert cfg.alpha.key == "from_a"
        assert cfg.beta.key == "from_b"
        # No cross-contamination:
        assert cfg.alpha.only_a == 1
        assert cfg.beta.only_b == 2
        assert "only_b" not in cfg.alpha
        assert "only_a" not in cfg.beta


# =============================================================================
# Full chain: defaults → file → app prefix env → overrides
# =============================================================================


class TestFullAppChain:
    """All four layers (when applicable) compose correctly for an app
    namespace.
    """

    def test_full_chain_overrides_win(self, tmp_path, monkeypatch) -> None:
        """All four sources mention ``alpha.key`` with different values;
        overrides_dict (highest) wins.
        """
        # Layer 3: namespaced file
        f = tmp_path / "alpha.toml"
        f.write_text('key = "from_file"\n')

        # Layer 4: env
        monkeypatch.setenv("APP_A_KEY", "from_env")

        cfg = Config(
            # Layer 1: app_defaults
            app_defaults={"alpha": {"key": "from_default"}},
            file_paths=[(str(f), "alpha")],
            app_prefixes={"alpha": "APP_A"},
            # Layer 5: overrides_dict
            overrides_dict={"alpha.key": "from_overrides"},
            load_dotenv_file=False,
        )
        assert cfg.alpha.key == "from_overrides"

    def test_partial_chain_each_layer_contributes(self, tmp_path, monkeypatch) -> None:
        """Different keys at different layers — all should survive."""
        f = tmp_path / "ns.toml"
        f.write_text('from_file = "f"\n')
        monkeypatch.setenv("APP_A_FROM_ENV", "e")
        cfg = Config(
            app_defaults={"alpha": {"from_default": "d"}},
            file_paths=[(str(f), "alpha")],
            app_prefixes={"alpha": "APP_A"},
            overrides_dict={"alpha.from_override": "o"},
            load_dotenv_file=False,
        )
        assert cfg.alpha.from_default == "d"
        assert cfg.alpha.from_file == "f"
        assert cfg.alpha.from_env == "e"
        assert cfg.alpha.from_override == "o"


# =============================================================================
# Edge cases
# =============================================================================


class TestAppEdgeCases:
    def test_app_on_nonexistent_creates_empty_config(self) -> None:
        cfg = Config(load_dotenv_file=False)
        sub = cfg.app("does_not_exist")
        assert isinstance(sub, Config)
        assert len(sub) == 0
        # The empty namespace was inserted into the parent for caching:
        assert "does_not_exist" in cfg
        assert cfg["does_not_exist"] is sub

    def test_app_namespace_with_list_value_returned_as_is(self) -> None:
        """If a top-level key happens to be a list (unusual but possible),
        ``app()`` returns it as-is rather than wrapping in Config.
        """
        cfg = Config(load_dotenv_file=False)
        dict.__setitem__(cfg, "mylist", [1, 2, 3])
        result = cfg.app("mylist")
        # The wrap branch only fires for raw dicts. Lists pass through.
        assert result == [1, 2, 3]

    def test_app_prefix_with_app_defaults_value_overridden(self, monkeypatch) -> None:
        """Verify the precedence: app_defaults (L1) < app_prefix env (L4)."""
        monkeypatch.setenv("MYAPP_PORT", "9999")
        cfg = Config(
            app_defaults={"myapp": {"port": 8080}},
            app_prefixes={"myapp": "MYAPP"},
            load_dotenv_file=False,
        )
        assert cfg.myapp.port == 9999

    def test_app_prefixes_without_app_defaults(self, monkeypatch) -> None:
        """``app_prefixes`` works even with no ``app_defaults`` — the
        env vars create the namespace.
        """
        monkeypatch.setenv("APP_C_KEY", "ad_hoc")
        cfg = Config(
            app_prefixes={"gamma": "APP_C"},
            load_dotenv_file=False,
        )
        assert cfg.gamma.key == "ad_hoc"
