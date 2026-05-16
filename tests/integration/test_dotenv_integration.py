# tests/integration/test_dotenv_integration.py
"""Integration tests for the .env file loading paths.

Specification reference
-----------------------
* ``confy/loader.py`` :meth:`Config._load_dotenv_file_action` (lines 660-699)

Path matrix covered
-------------------
* **Implicit search** of CWD for ``.env`` (the default behavior).
* **Explicit ``dotenv_path``** — load a specific file.
* **``load_dotenv_file=False``** disables all loading.
* **``override=False`` semantics** — pre-existing env vars win over .env.
* **python-dotenv not installed** — graceful warning, no crash
  (lines 663-678).
* **dotenv loading raises** — graceful warning, no crash (lines 693-697).
* **.env contains both prefixed and unprefixed vars** — only the
  prefix-matching ones end up in the Config.

Test design
-----------
We never rely on the real CWD's .env file. Each test creates an isolated
temp dir and chdir's there. The autouse ``_env_snapshot`` fixture in
``conftest.py`` ensures pre-existing env vars from other tests don't
bleed in.

Where we exercise the "python-dotenv missing" branch, we monkeypatch
``confy.loader.load_dotenv`` and ``confy.loader.find_dotenv`` to ``None``
to simulate the import failure without uninstalling the package.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

import confy.loader as loader_mod
from confy.loader import Config

# Skip the whole module if python-dotenv genuinely isn't installed in this env.
pytest.importorskip("dotenv")

pytestmark = pytest.mark.integration


# =============================================================================
# Implicit .env discovery (default behavior)
# =============================================================================


class TestImplicitDotenv:
    """``load_dotenv_file=True`` (default) searches CWD for ``.env``."""

    def test_loads_from_cwd(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("MYAPP_KEY=from_dotenv\n")
        monkeypatch.chdir(tmp_path)
        cfg = Config(prefix="MYAPP")
        assert cfg.key == "from_dotenv"

    def test_loads_multiple_keys(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("MYAPP_KEY1=v1\nMYAPP_KEY2=v2\nUNRELATED=skip_me\n")
        monkeypatch.chdir(tmp_path)
        cfg = Config(prefix="MYAPP")
        assert cfg.key1 == "v1"
        assert cfg.key2 == "v2"
        # UNRELATED isn't prefixed → not in cfg
        assert "unrelated" not in cfg

    def test_no_dotenv_file_in_cwd_no_error(self, tmp_path, monkeypatch) -> None:
        """Absent .env is not an error — config builds normally from
        defaults only.
        """
        monkeypatch.chdir(tmp_path)  # empty dir
        cfg = Config(defaults={"a": 1}, prefix="MYAPP")
        assert cfg.a == 1


# =============================================================================
# Explicit dotenv_path
# =============================================================================


class TestExplicitDotenvPath:
    """``dotenv_path=...`` loads that specific file, ignoring CWD search."""

    def test_explicit_path(self, tmp_path) -> None:
        elsewhere = tmp_path / "config_dir" / "settings.env"
        elsewhere.parent.mkdir()
        elsewhere.write_text("MYAPP_K=v\n")
        # Note: NOT chdir'ing into config_dir. Implicit search wouldn't
        # find this file from any natural CWD.
        cfg = Config(
            prefix="MYAPP",
            dotenv_path=str(elsewhere),
        )
        assert cfg.k == "v"

    def test_explicit_path_overrides_implicit_search(
        self, tmp_path, monkeypatch
    ) -> None:
        """A .env in CWD is ignored when an explicit path is given."""
        cwd_env = tmp_path / ".env"
        cwd_env.write_text("MYAPP_K=cwd_value\n")
        other_env = tmp_path / "other.env"
        other_env.write_text("MYAPP_K=other_value\n")
        monkeypatch.chdir(tmp_path)
        cfg = Config(prefix="MYAPP", dotenv_path=str(other_env))
        assert cfg.k == "other_value"


# =============================================================================
# load_dotenv_file=False
# =============================================================================


class TestDotenvDisabled:
    """When ``load_dotenv_file=False``, .env files are not consulted at all."""

    def test_cwd_dotenv_ignored(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("MYAPP_K=from_dotenv\n")
        monkeypatch.chdir(tmp_path)
        cfg = Config(prefix="MYAPP", load_dotenv_file=False)
        # The .env file is present but NOT loaded.
        assert "k" not in cfg

    def test_explicit_path_ignored_when_disabled(self, tmp_path) -> None:
        env_file = tmp_path / "explicit.env"
        env_file.write_text("MYAPP_K=v\n")
        cfg = Config(
            prefix="MYAPP",
            dotenv_path=str(env_file),
            load_dotenv_file=False,
        )
        assert "k" not in cfg


# =============================================================================
# override=False: pre-existing env vars win
# =============================================================================


class TestDotenvOverrideSemantics:
    """python-dotenv is called with ``override=False`` (loader.py line
    686), so a pre-existing env var is NOT overwritten by .env contents.
    """

    def test_preset_env_wins(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("MYAPP_K=from_dotenv\n")
        monkeypatch.chdir(tmp_path)
        # Pre-set the same key BEFORE Config init:
        monkeypatch.setenv("MYAPP_K", "preset")
        cfg = Config(prefix="MYAPP")
        assert cfg.k == "preset"

    def test_dotenv_fills_gaps(self, tmp_path, monkeypatch) -> None:
        """A .env var NOT pre-set in the environment IS loaded."""
        env_file = tmp_path / ".env"
        env_file.write_text("MYAPP_A=from_dotenv_a\nMYAPP_B=from_dotenv_b\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("MYAPP_A", "preset_a")
        cfg = Config(prefix="MYAPP")
        assert cfg.a == "preset_a"  # pre-existing won
        assert cfg.b == "from_dotenv_b"  # .env filled gap


# =============================================================================
# python-dotenv missing simulation (lines 663-678)
# =============================================================================


class TestDotenvLibraryMissing:
    """Simulates a runtime where python-dotenv isn't importable. Confy
    must log a warning and continue (no crash).
    """

    def test_missing_library_with_dotenv_present_warns(
        self, tmp_path, monkeypatch, caplog
    ) -> None:
        # Make the loader behave as if the library import failed.
        monkeypatch.setattr(loader_mod, "load_dotenv", None)
        monkeypatch.setattr(loader_mod, "find_dotenv", None)
        env_file = tmp_path / ".env"
        env_file.write_text("MYAPP_K=v\n")
        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            cfg = Config(prefix="MYAPP", dotenv_path=str(env_file))
        # Config builds, no exception, but the .env isn't loaded:
        assert "k" not in cfg
        # And we should see a warning about the missing library:
        assert any(
            "python-dotenv" in r.message and "not installed" in r.message
            for r in caplog.records
        )

    def test_missing_library_without_dotenv_silent(
        self, tmp_path, monkeypatch, caplog
    ) -> None:
        """When the library is missing AND there's no .env file to load,
        we shouldn't even warn (no work was needed).
        """
        monkeypatch.setattr(loader_mod, "load_dotenv", None)
        monkeypatch.setattr(loader_mod, "find_dotenv", None)
        monkeypatch.chdir(tmp_path)  # empty dir, no .env
        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            cfg = Config(prefix="MYAPP")
        # No warnings about python-dotenv:
        relevant = [r for r in caplog.records if "python-dotenv" in r.message]
        assert relevant == []

    def test_missing_load_but_find_works_uses_find_dotenv(
        self, tmp_path, monkeypatch, caplog
    ) -> None:
        """Lines 666-669: ``load_dotenv`` is missing but ``find_dotenv``
        is still callable. With no explicit ``dotenv_path``, the code
        calls ``find_dotenv(usecwd=True)`` to discover one. If found,
        the existence check + warning logic fires.
        """
        env_file = tmp_path / ".env"
        env_file.write_text("MYAPP_K=v\n")
        monkeypatch.chdir(tmp_path)

        monkeypatch.setattr(loader_mod, "load_dotenv", None)

        # Leave find_dotenv as a callable that points to our temp file.
        def fake_find_dotenv(usecwd=False):
            return str(env_file)

        monkeypatch.setattr(loader_mod, "find_dotenv", fake_find_dotenv)

        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            cfg = Config(prefix="MYAPP")  # no explicit dotenv_path
        # The .env file was found AND the missing-library warning fires:
        assert any(
            "python-dotenv" in r.message and str(env_file) in r.message
            for r in caplog.records
        )
        # And of course nothing was actually loaded:
        assert "k" not in cfg

    def test_find_dotenv_exception_is_swallowed(
        self, tmp_path, monkeypatch, caplog
    ) -> None:
        """Lines 671-672: when ``find_dotenv`` itself raises during
        discovery (e.g., filesystem error), the exception is swallowed
        and the no-op return is taken. No crash, no warning.
        """
        monkeypatch.setattr(loader_mod, "load_dotenv", None)

        def raising_find(usecwd=False):
            raise OSError("simulated find_dotenv failure")

        monkeypatch.setattr(loader_mod, "find_dotenv", raising_find)
        monkeypatch.chdir(tmp_path)

        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            # Should NOT raise:
            cfg = Config(prefix="MYAPP")
        # No "python-dotenv not installed" warning because the existence
        # check never completed.
        assert isinstance(cfg, Config)


# =============================================================================
# Dotenv loading raises (lines 693-697)
# =============================================================================


class TestDotenvLoadRaises:
    """If python-dotenv's ``load_dotenv()`` itself raises (e.g., I/O
    failure during read), confy must swallow it and warn rather than
    propagating.
    """

    def test_oserror_during_load(self, tmp_path, monkeypatch, caplog) -> None:
        def raising_loader(*args, **kwargs):
            raise OSError("simulated I/O failure")

        monkeypatch.setattr(loader_mod, "load_dotenv", raising_loader)
        env_file = tmp_path / ".env"
        env_file.write_text("MYAPP_K=v\n")
        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            # Should NOT raise:
            cfg = Config(prefix="MYAPP", dotenv_path=str(env_file))
        # Config still constructs:
        assert isinstance(cfg, Config)
        # Warning is logged:
        assert any(
            "Failed during .env file loading" in r.message for r in caplog.records
        )
        # And ``simulated I/O failure`` makes it into the message:
        assert any("simulated I/O failure" in r.message for r in caplog.records)

    def test_load_returns_false_no_warning(self, tmp_path, monkeypatch, caplog) -> None:
        """Line 693: ``load_dotenv`` returns ``False`` (file present but
        all variables already exist in env, so nothing was actually
        loaded). This is a DEBUG message path, not a warning.
        """

        def fake_loader(*args, **kwargs):
            return False  # found file, but didn't change env

        monkeypatch.setattr(loader_mod, "load_dotenv", fake_loader)
        env_file = tmp_path / ".env"
        env_file.write_text("MYAPP_K=v\n")
        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            cfg = Config(prefix="MYAPP", dotenv_path=str(env_file))
        # No warnings — this is an expected, non-erroneous state:
        relevant_warnings = [
            r for r in caplog.records if "Failed" in r.message or "Warning" in r.message
        ]
        assert relevant_warnings == []
        # Config builds normally:
        assert isinstance(cfg, Config)


# =============================================================================
# Integration with the precedence chain
# =============================================================================


class TestDotenvInPrecedenceChain:
    """.env values flow through the env-vars layer (L4), so they obey the
    standard precedence: defaults < .env < overrides_dict.
    """

    def test_dotenv_beats_defaults(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("MYAPP_K=from_dotenv\n")
        monkeypatch.chdir(tmp_path)
        cfg = Config(defaults={"k": "from_defaults"}, prefix="MYAPP")
        assert cfg.k == "from_dotenv"

    def test_overrides_beat_dotenv(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("MYAPP_K=from_dotenv\n")
        monkeypatch.chdir(tmp_path)
        cfg = Config(
            prefix="MYAPP",
            overrides_dict={"k": "from_overrides"},
        )
        assert cfg.k == "from_overrides"
