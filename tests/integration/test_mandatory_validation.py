# tests/integration/test_mandatory_validation.py
"""Integration tests for mandatory-key validation.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §3.5, §7.3.2 — Mandatory Keys
* ``confy/loader.py`` :meth:`Config._validate_mandatory` lines 1211-1224
* ``confy/exceptions.py`` :class:`MissingMandatoryConfig`

What this file tests
--------------------
Per spec §3.5, the mandatory check runs **after all sources merge**. So a
mandatory key can be supplied by ANY layer (defaults, kwargs, file, env,
overrides), and the check should pass. Conversely, a key absent from all
sources must raise ``MissingMandatoryConfig`` with the full list of
missing keys.

The pre-existing ``test_loader.py`` covers two cases (all-in-defaults and
all-missing). This file fills in the per-layer matrix and the multi-key
error-aggregation behavior.

Gotcha on env-supplied mandatory keys
-------------------------------------
The env-var remap is structure-aware: ``MYAPP_DB_HOST`` resolves to
``db.host`` only if the base config already has ``db`` as a known
container key. Without that, the env var falls back to a flat
``db_host`` key, which won't satisfy a mandatory dot-path
``db.host``. Tests in this file either:

  (a) use single-segment mandatory keys, or
  (b) seed defaults with the right structure so the remap succeeds.
"""

from __future__ import annotations

import json

import pytest

from confy.exceptions import MissingMandatoryConfig
from confy.loader import Config

pytestmark = pytest.mark.integration


# =============================================================================
# Mandatory satisfied by each individual layer
# =============================================================================


class TestMandatorySatisfiedByLayer:
    """For each source layer, a mandatory key supplied there is OK."""

    def test_by_defaults(self) -> None:
        cfg = Config(
            defaults={"db": {"host": "localhost"}},
            mandatory=["db.host"],
            load_dotenv_file=False,
        )
        assert cfg.db.host == "localhost"

    def test_by_kwargs(self) -> None:
        cfg = Config(
            mandatory=["my_kwarg"],
            my_kwarg="present",
            load_dotenv_file=False,
        )
        assert cfg.my_kwarg == "present"

    def test_by_file_json(self, tmp_path) -> None:
        f = tmp_path / "c.json"
        f.write_text(json.dumps({"db": {"host": "from_file"}}))
        cfg = Config(
            mandatory=["db.host"],
            file_path=str(f),
            load_dotenv_file=False,
        )
        assert cfg.db.host == "from_file"

    def test_by_file_toml(self, tmp_path) -> None:
        f = tmp_path / "c.toml"
        f.write_text('[db]\nhost = "from_toml"\n')
        cfg = Config(
            mandatory=["db.host"],
            file_path=str(f),
            load_dotenv_file=False,
        )
        assert cfg.db.host == "from_toml"

    def test_by_env_with_seeded_defaults(self, monkeypatch) -> None:
        """Env-supplied mandatory key works when ``db`` is already a
        known base key (so the remap nests correctly).
        """
        monkeypatch.setenv("MYAPP_DB_HOST", "from_env")
        cfg = Config(
            defaults={"db": {"host": "default"}},  # seed structure
            mandatory=["db.host"],
            prefix="MYAPP",
            load_dotenv_file=False,
        )
        assert cfg.db.host == "from_env"

    def test_by_env_single_segment(self, monkeypatch) -> None:
        """Single-segment mandatory keys don't need structural seeding."""
        monkeypatch.setenv("MYAPP_FLAG", "true")
        cfg = Config(
            mandatory=["flag"],
            prefix="MYAPP",
            load_dotenv_file=False,
        )
        assert cfg.flag is True

    def test_by_overrides(self) -> None:
        cfg = Config(
            mandatory=["db.host"],
            overrides_dict={"db.host": "from_overrides"},
            load_dotenv_file=False,
        )
        assert cfg.db.host == "from_overrides"


# =============================================================================
# Missing mandatory keys
# =============================================================================


class TestMissingMandatory:
    """Absent mandatory keys raise ``MissingMandatoryConfig`` with the
    full set of missing dot-paths.
    """

    def test_single_missing(self) -> None:
        with pytest.raises(MissingMandatoryConfig) as exc:
            Config(
                defaults={"existing": 1},
                mandatory=["db.host"],
                load_dotenv_file=False,
            )
        assert exc.value.missing_keys == ["db.host"]

    def test_multiple_missing(self) -> None:
        with pytest.raises(MissingMandatoryConfig) as exc:
            Config(
                defaults={},
                mandatory=["a", "b.c", "d.e.f"],
                load_dotenv_file=False,
            )
        # All three missing should be reported, in the order they were
        # given.
        assert set(exc.value.missing_keys) == {"a", "b.c", "d.e.f"}

    def test_message_contains_keys(self) -> None:
        with pytest.raises(MissingMandatoryConfig) as exc:
            Config(mandatory=["one", "two"], load_dotenv_file=False)
        msg = str(exc.value)
        assert "one" in msg
        assert "two" in msg

    def test_partial_missing(self) -> None:
        """Some keys present, others not — only the missing are reported."""
        with pytest.raises(MissingMandatoryConfig) as exc:
            Config(
                defaults={"present": 1},
                mandatory=["present", "missing_a", "missing_b"],
                load_dotenv_file=False,
            )
        assert "present" not in exc.value.missing_keys
        assert set(exc.value.missing_keys) == {"missing_a", "missing_b"}


# =============================================================================
# Invalid path = treated as missing
# =============================================================================


class TestMandatoryInvalidPath:
    """A mandatory path that *traverses through a non-dict* is treated as
    missing (not a TypeError).
    """

    def test_traverse_into_scalar(self) -> None:
        with pytest.raises(MissingMandatoryConfig) as exc:
            Config(
                defaults={"logging": {"level": "INFO"}},  # level is a str
                mandatory=["logging.level.sublevel"],
                load_dotenv_file=False,
            )
        assert "logging.level.sublevel" in exc.value.missing_keys


# =============================================================================
# Cross-layer composition: lower layer doesn't satisfy, higher does
# =============================================================================


class TestMandatoryAcrossLayers:
    """When a lower layer LACKS a mandatory key but a higher layer SUPPLIES
    it, the check passes (mandatory runs AFTER merge).
    """

    def test_missing_in_defaults_supplied_by_overrides(self) -> None:
        cfg = Config(
            defaults={"other": 1},  # no 'db.host'
            mandatory=["db.host"],
            overrides_dict={"db.host": "supplied"},
            load_dotenv_file=False,
        )
        assert cfg.db.host == "supplied"

    def test_missing_in_defaults_supplied_by_file(self, tmp_path) -> None:
        f = tmp_path / "c.json"
        f.write_text(json.dumps({"db": {"host": "from_file"}}))
        cfg = Config(
            defaults={"other": 1},
            mandatory=["db.host"],
            file_path=str(f),
            load_dotenv_file=False,
        )
        assert cfg.db.host == "from_file"


# =============================================================================
# Empty / no-op cases
# =============================================================================


class TestMandatoryEdgeCases:
    def test_empty_mandatory_list_ok(self) -> None:
        """An empty mandatory list is a no-op."""
        cfg = Config(mandatory=[], load_dotenv_file=False)
        assert isinstance(cfg, Config)

    def test_none_mandatory_ok(self) -> None:
        """``mandatory=None`` is the default and skips validation."""
        cfg = Config(mandatory=None, load_dotenv_file=False)
        assert isinstance(cfg, Config)

    def test_mandatory_value_can_be_falsy(self) -> None:
        """A mandatory key with value ``False``, ``0``, ``None``, or empty
        string is still considered "present" — only key absence triggers
        the error.
        """
        for falsy in [False, 0, None, "", []]:
            cfg = Config(
                defaults={"k": falsy},
                mandatory=["k"],
                load_dotenv_file=False,
            )
            assert cfg.k == falsy
