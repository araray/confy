# tests/integration/test_precedence_matrix.py
"""Integration tests for the 5-layer precedence contract.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §3.6 — Precedence Order
* ``CONFY_DESIGN_SPECIFICATION.md`` §7.3.1 — Precedence Order Tests
* ``confy/loader.py`` :meth:`Config.__init__` (lines 387-658)

The precedence contract (lowest → highest)
------------------------------------------
============  =====================================================
Layer         Source
============  =====================================================
L1 defaults   ``defaults=...`` constructor arg
L2 kwargs     ``**kwargs`` constructor arg (and rare ``*args``)
L3 file       ``file_path=...`` and ``file_paths=...``
L4 env        environment variables (``prefix=...``, ``app_prefixes=...``,
              and variables loaded from a ``.env`` file)
L5 overrides  ``overrides_dict=...`` constructor arg
============  =====================================================

What this file tests
--------------------
The 10 pairwise precedence relations Lᵢ > Lⱼ (j < i), plus a single
full-stack test that exercises all 5 layers competing for the same key
to verify the global ordering. Each relation is tested in **isolation**
— one key, two layers, lower vs higher — so a failure points at exactly
one boundary.

Tests use ``load_dotenv_file=False`` everywhere to avoid implicit .env
discovery side-effects.
"""

from __future__ import annotations

import json

import pytest

from confy.loader import Config

pytestmark = pytest.mark.integration


# =============================================================================
# Helpers
# =============================================================================


@pytest.fixture
def json_file(tmp_path):
    """Factory: write a JSON file with given content, return its path."""

    def _make(content: dict) -> str:
        f = tmp_path / "config.json"
        f.write_text(json.dumps(content))
        return str(f)

    return _make


# =============================================================================
# Single-key pairwise relations
# =============================================================================


class TestL2OverL1:
    """kwargs (L2) > defaults (L1)."""

    def test_kwargs_overrides_defaults(self) -> None:
        cfg = Config(
            defaults={"shared": "from_defaults"},
            shared="from_kwargs",
            load_dotenv_file=False,
        )
        assert cfg.shared == "from_kwargs"


class TestL3OverL1:
    """file (L3) > defaults (L1)."""

    def test_file_overrides_defaults(self, json_file) -> None:
        fp = json_file({"shared": "from_file"})
        cfg = Config(
            defaults={"shared": "from_defaults"},
            file_path=fp,
            load_dotenv_file=False,
        )
        assert cfg.shared == "from_file"


class TestL3OverL2:
    """file (L3) > kwargs (L2)."""

    def test_file_overrides_kwargs(self, json_file) -> None:
        fp = json_file({"shared": "from_file"})
        cfg = Config(
            file_path=fp,
            shared="from_kwargs",
            load_dotenv_file=False,
        )
        assert cfg.shared == "from_file"


class TestL4OverL1:
    """env (L4) > defaults (L1)."""

    def test_env_overrides_defaults(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_SHARED", "from_env")
        cfg = Config(
            defaults={"shared": "from_defaults"},
            prefix="MYAPP",
            load_dotenv_file=False,
        )
        assert cfg.shared == "from_env"


class TestL4OverL2:
    """env (L4) > kwargs (L2)."""

    def test_env_overrides_kwargs(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_SHARED", "from_env")
        cfg = Config(
            shared="from_kwargs",
            prefix="MYAPP",
            load_dotenv_file=False,
        )
        assert cfg.shared == "from_env"


class TestL4OverL3:
    """env (L4) > file (L3)."""

    def test_env_overrides_file(self, json_file, monkeypatch) -> None:
        fp = json_file({"shared": "from_file"})
        monkeypatch.setenv("MYAPP_SHARED", "from_env")
        cfg = Config(
            file_path=fp,
            prefix="MYAPP",
            load_dotenv_file=False,
        )
        assert cfg.shared == "from_env"


class TestL5OverL1:
    """overrides (L5) > defaults (L1)."""

    def test_overrides_beats_defaults(self) -> None:
        cfg = Config(
            defaults={"shared": "from_defaults"},
            overrides_dict={"shared": "from_overrides"},
            load_dotenv_file=False,
        )
        assert cfg.shared == "from_overrides"


class TestL5OverL2:
    """overrides (L5) > kwargs (L2)."""

    def test_overrides_beats_kwargs(self) -> None:
        cfg = Config(
            shared="from_kwargs",
            overrides_dict={"shared": "from_overrides"},
            load_dotenv_file=False,
        )
        assert cfg.shared == "from_overrides"


class TestL5OverL3:
    """overrides (L5) > file (L3)."""

    def test_overrides_beats_file(self, json_file) -> None:
        fp = json_file({"shared": "from_file"})
        cfg = Config(
            file_path=fp,
            overrides_dict={"shared": "from_overrides"},
            load_dotenv_file=False,
        )
        assert cfg.shared == "from_overrides"


class TestL5OverL4:
    """overrides (L5) > env (L4)."""

    def test_overrides_beats_env(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_SHARED", "from_env")
        cfg = Config(
            prefix="MYAPP",
            overrides_dict={"shared": "from_overrides"},
            load_dotenv_file=False,
        )
        assert cfg.shared == "from_overrides"


# =============================================================================
# Full-stack test: all 5 sources compete
# =============================================================================


class TestFullStack:
    """All 5 sources set the same key; L5 must win, and ALL non-conflicting
    keys from lower layers must survive."""

    def test_all_five_layers(self, json_file, monkeypatch) -> None:
        """Five sources, five distinct values for ``shared``, plus one
        key unique to each layer. The expected outcome:

        - ``shared`` == ``"L5"`` (overrides_dict wins)
        - ``l1_only``, ``l2_only``, ``l3_only``, ``l4_only``, ``l5_only``
          each from their own layer
        """
        fp = json_file(
            {
                "shared": "L3",
                "l3_only": "from_file",
            }
        )
        monkeypatch.setenv("MYAPP_SHARED", "L4")
        monkeypatch.setenv("MYAPP_L4_ONLY", "from_env")
        cfg = Config(
            defaults={"shared": "L1", "l1_only": "from_defaults"},
            file_path=fp,
            prefix="MYAPP",
            overrides_dict={"shared": "L5", "l5_only": "from_overrides"},
            shared_kwarg="L2_kwarg",  # avoid kwarg name 'shared' (collides with defaults arg? no, kwargs go to **kwargs)
            shared="L2",  # this goes to **kwargs since 'shared' isn't a named param
            l2_only="from_kwargs",
            load_dotenv_file=False,
        )
        # L5 wins:
        assert cfg.shared == "L5"
        # All unique-to-layer keys survive:
        assert cfg.l1_only == "from_defaults"
        assert cfg.l2_only == "from_kwargs"
        assert cfg.l3_only == "from_file"
        assert cfg.l4_only == "from_env"
        assert cfg.l5_only == "from_overrides"


# =============================================================================
# Nested-key precedence (does layering work with nested keys?)
# =============================================================================


class TestNestedKeyPrecedence:
    """Precedence must apply at every depth, not just top level."""

    def test_nested_file_over_defaults(self, json_file) -> None:
        fp = json_file({"db": {"host": "from_file"}})
        cfg = Config(
            defaults={"db": {"host": "from_defaults", "port": 5432}},
            file_path=fp,
            load_dotenv_file=False,
        )
        assert cfg.db.host == "from_file"
        assert cfg.db.port == 5432  # unique to defaults — preserved

    def test_nested_env_over_file(self, json_file, monkeypatch) -> None:
        fp = json_file({"db": {"host": "from_file", "port": 5432}})
        monkeypatch.setenv("MYAPP_DB_HOST", "from_env")
        cfg = Config(
            file_path=fp,
            prefix="MYAPP",
            load_dotenv_file=False,
        )
        assert cfg.db.host == "from_env"
        assert cfg.db.port == 5432  # not in env — preserved from file

    def test_nested_overrides_over_env(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_DB_HOST", "from_env")
        cfg = Config(
            prefix="MYAPP",
            overrides_dict={"db.host": "from_overrides"},
            load_dotenv_file=False,
        )
        assert cfg.db.host == "from_overrides"


# =============================================================================
# Non-conflicting keys: every source's unique keys survive
# =============================================================================


class TestNonConflictingKeysSurvive:
    """When sources contribute disjoint keys, all keys appear in the
    merged result regardless of their source layer."""

    def test_all_layers_disjoint(self, json_file, monkeypatch) -> None:
        fp = json_file({"file_key": "f"})
        monkeypatch.setenv("MYAPP_ENV_KEY", "e")
        cfg = Config(
            defaults={"default_key": "d"},
            file_path=fp,
            prefix="MYAPP",
            overrides_dict={"override_key": "o"},
            kwarg_key="k",
            load_dotenv_file=False,
        )
        assert cfg.default_key == "d"
        assert cfg.kwarg_key == "k"
        assert cfg.file_key == "f"
        assert cfg.env_key == "e"
        assert cfg.override_key == "o"


# =============================================================================
# Type-changing overrides (e.g., env override changes int to str)
# =============================================================================


class TestTypeChangingOverrides:
    """A higher-precedence source can change a value's *type*.

    This is documented behavior: each layer's value wholesale replaces
    the lower layer's, so a string-typed env var can replace an integer
    default. The new value goes through ``_parse_value`` though, so
    ``"42"`` becomes ``42`` again at the env layer.
    """

    def test_env_parse_restores_int(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_PORT", "9090")
        cfg = Config(
            defaults={"port": 8080},
            prefix="MYAPP",
            load_dotenv_file=False,
        )
        assert cfg.port == 9090
        assert isinstance(cfg.port, int)

    def test_env_bool_parsing_in_chain(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_FLAG", "true")
        cfg = Config(
            defaults={"flag": False},
            prefix="MYAPP",
            load_dotenv_file=False,
        )
        assert cfg.flag is True

    def test_overrides_dict_parses_string_values(self) -> None:
        cfg = Config(
            defaults={"port": 8080},
            overrides_dict={"port": "9090"},
            load_dotenv_file=False,
        )
        # _structure_overrides also goes through _parse_value:
        assert cfg.port == 9090
        assert isinstance(cfg.port, int)
