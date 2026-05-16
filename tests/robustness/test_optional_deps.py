# tests/robustness/test_optional_deps.py
"""Robustness tests for missing optional dependencies.

Specification reference
-----------------------
* ``confy/loader.py`` lines 34-46 (ImportError fallback for tomli, dotenv)
* ``confy/loader.py`` lines 731-732 (RuntimeError when tomli is None)
* ``confy/loader.py`` lines 800-803 (RuntimeError when tomli is None, multi-file path)

Why this matters
----------------
Confy declares ``tomli`` and ``python-dotenv`` as conditional/optional
dependencies. Users on Python 3.11+ get :mod:`tomllib` from stdlib;
on older Python, ``tomli`` is required for TOML. ``python-dotenv``
is only needed if you actually use ``.env`` files.

These tests verify that:

1. When ``tomli`` is unavailable at runtime, loading a TOML file
   raises a clear :class:`RuntimeError` (not a confusing
   AttributeError or NameError).
2. When ``python-dotenv`` is unavailable but a ``.env`` file is
   present, the loader logs a warning and skips it (covered
   extensively in :mod:`tests.integration.test_dotenv_integration`;
   this file adds the *consequence-on-other-paths* tests).
3. When BOTH are missing but the user does NOT use TOML or .env
   files, configs still load fine.

Test technique
--------------
Rather than actually uninstalling the libraries (which would break the
test runner itself), we monkey-patch the module attributes
``confy.loader.tomli``, ``confy.loader.load_dotenv``, and
``confy.loader.find_dotenv`` to simulate the ImportError state. The
loader reads these as module globals on every call, so the patch
takes effect immediately.
"""

from __future__ import annotations

import json
import logging

import pytest

import confy.loader as loader_mod
from confy.loader import Config

pytestmark = pytest.mark.robustness


# =============================================================================
# tomli missing
# =============================================================================


class TestTomliMissing:
    """Simulates a runtime where ``tomli`` couldn't be imported."""

    def test_toml_file_path_raises_runtime_error(self, monkeypatch, tmp_path) -> None:
        """Line 800-803 in loader.py: loading a .toml via ``file_path``
        when tomli is None raises :class:`RuntimeError` with a clear
        message.
        """
        monkeypatch.setattr(loader_mod, "tomli", None)
        toml_file = tmp_path / "c.toml"
        toml_file.write_text("a = 1\n")
        with pytest.raises(RuntimeError, match="(?i)tomli"):
            Config(file_path=str(toml_file), load_dotenv_file=False)

    def test_toml_file_paths_namespaced_skipped_with_warning(
        self, monkeypatch, tmp_path, caplog
    ) -> None:
        """Line 731-732 chain via the multi-file path: a namespaced TOML
        file in ``file_paths`` with tomli=None triggers the inner
        RuntimeError, which is caught by the multi-file handler and
        converted to a warning. The other file(s) still load.
        """
        monkeypatch.setattr(loader_mod, "tomli", None)
        json_file = tmp_path / "good.json"
        json_file.write_text(json.dumps({"k": "v"}))
        toml_file = tmp_path / "bad.toml"
        toml_file.write_text("a = 1\n")

        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            cfg = Config(
                file_paths=[(str(json_file), "good"), (str(toml_file), "bad")],
                load_dotenv_file=False,
            )

        # JSON file loaded into its namespace:
        assert cfg.good.k == "v"
        # TOML file was skipped:
        assert "bad" not in cfg
        # Warning includes the problematic path:
        assert any("bad.toml" in r.message for r in caplog.records)

    def test_toml_file_in_non_namespaced_file_paths_skipped(
        self, monkeypatch, tmp_path, caplog
    ) -> None:
        """Same as above but for non-namespaced ``file_paths`` entries."""
        monkeypatch.setattr(loader_mod, "tomli", None)
        json_file = tmp_path / "good.json"
        json_file.write_text(json.dumps({"k": "v"}))
        toml_file = tmp_path / "bad.toml"
        toml_file.write_text("a = 1\n")

        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            cfg = Config(
                file_paths=[str(json_file), str(toml_file)],
                load_dotenv_file=False,
            )
        # JSON file still loaded:
        assert cfg.k == "v"
        # Warning was emitted:
        assert any("bad.toml" in r.message for r in caplog.records)

    def test_json_only_works_fine_without_tomli(self, monkeypatch, tmp_path) -> None:
        """The big test: if a user never touches TOML, missing tomli is
        invisible.
        """
        monkeypatch.setattr(loader_mod, "tomli", None)
        json_file = tmp_path / "c.json"
        json_file.write_text(json.dumps({"k": "v"}))
        cfg = Config(file_path=str(json_file), load_dotenv_file=False)
        assert cfg.k == "v"

    def test_defaults_only_works_without_tomli(self, monkeypatch) -> None:
        """A pure programmatic Config with no file at all needs neither
        optional dep.
        """
        monkeypatch.setattr(loader_mod, "tomli", None)
        cfg = Config(defaults={"a": 1}, load_dotenv_file=False)
        assert cfg.a == 1


# =============================================================================
# python-dotenv missing
# =============================================================================


class TestDotenvMissing:
    """python-dotenv missing scenarios. The detailed paths are covered
    in :mod:`tests.integration.test_dotenv_integration`; this file pins
    that other Config features keep working when dotenv is None.
    """

    def test_config_init_succeeds_without_dotenv(self, monkeypatch) -> None:
        """The Config class must construct cleanly with dotenv=None when
        no .env file is requested.
        """
        monkeypatch.setattr(loader_mod, "load_dotenv", None)
        monkeypatch.setattr(loader_mod, "find_dotenv", None)
        cfg = Config(
            defaults={"k": "v"},
            load_dotenv_file=False,
        )
        assert cfg.k == "v"

    def test_no_dotenv_file_no_warning_when_disabled(self, monkeypatch, caplog) -> None:
        """If both python-dotenv is missing AND ``load_dotenv_file=False``,
        we should see no warnings at all about .env files.
        """
        monkeypatch.setattr(loader_mod, "load_dotenv", None)
        monkeypatch.setattr(loader_mod, "find_dotenv", None)
        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            Config(defaults={"k": "v"}, load_dotenv_file=False)
        dotenv_warnings = [r for r in caplog.records if ".env" in r.message]
        assert dotenv_warnings == []

    def test_env_vars_still_work_without_dotenv(self, monkeypatch) -> None:
        """Plain os.environ env vars (without a .env file) work fine."""
        monkeypatch.setattr(loader_mod, "load_dotenv", None)
        monkeypatch.setattr(loader_mod, "find_dotenv", None)
        monkeypatch.setenv("MYAPP_K", "from_env")
        cfg = Config(
            prefix="MYAPP",
            load_dotenv_file=False,
        )
        assert cfg.k == "from_env"


# =============================================================================
# Both missing simultaneously
# =============================================================================


class TestBothMissing:
    """The "minimal install" case: only json + os.environ available."""

    def test_json_plus_env_vars_works(self, monkeypatch, tmp_path) -> None:
        """Even with both optional deps missing, the bread-and-butter
        case (JSON file + env vars) still works.
        """
        monkeypatch.setattr(loader_mod, "tomli", None)
        monkeypatch.setattr(loader_mod, "load_dotenv", None)
        monkeypatch.setattr(loader_mod, "find_dotenv", None)
        monkeypatch.setenv("MYAPP_OVERRIDE", "from_env")

        cfg_file = tmp_path / "c.json"
        cfg_file.write_text(json.dumps({"base": 1}))

        cfg = Config(
            file_path=str(cfg_file),
            prefix="MYAPP",
            load_dotenv_file=False,
        )
        assert cfg.base == 1
        assert cfg.override == "from_env"

    def test_pure_programmatic_works(self, monkeypatch) -> None:
        monkeypatch.setattr(loader_mod, "tomli", None)
        monkeypatch.setattr(loader_mod, "load_dotenv", None)
        monkeypatch.setattr(loader_mod, "find_dotenv", None)
        cfg = Config(
            defaults={"a": 1, "b": {"c": 2}},
            overrides_dict={"a": 99},
            load_dotenv_file=False,
        )
        assert cfg.a == 99
        assert cfg.b.c == 2
