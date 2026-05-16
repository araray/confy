# tests/integration/test_multifile.py
"""Integration tests for multi-file loading and TOML key promotion.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §3.5 (Sources), §5.3.4 (File loading)
* ``confy/loader.py`` ``__init__`` lines 455-523 (multi-file processing)
* ``confy/loader.py`` ``_load_config_file`` lines 784-845 (TOML promotion)

What this file fills in beyond ``tests/v040/test_phase1_multifile.py``
---------------------------------------------------------------------
* **Lines 482-484** — namespaced file in ``file_paths`` that parses-fails:
  warning logged, that file skipped, others succeed.
* **Lines 516-517** — non-namespaced file in ``file_paths`` that
  parses-fails (non-FileNotFoundError): warning logged, skipped.
* **Line 829** — TOML key promotion: "already exists at root" warning
  when both a root-level key AND an in-section key with the same name
  exist; the root one wins, the section one is skipped with a warning.
* **Lines 833-836** — empty TOML section removal after promotion: if
  the section had ONLY a promotable key, it's deleted from file_content
  afterwards.
* **Line 842** — unsupported file extension via ``file_path`` raises
  with a clear message.
* **Line 732** — ``_load_single_file`` JSON-parse failure path.
"""

from __future__ import annotations

import json
import logging

import pytest

from confy.loader import Config

pytestmark = pytest.mark.integration


# =============================================================================
# Multi-file basic + edge cases
# =============================================================================


class TestMultiFileBasic:
    """Standard merging order: later file wins on conflicts."""

    def test_two_json_files(self, tmp_path) -> None:
        f1 = tmp_path / "a.json"
        f1.write_text(json.dumps({"x": "from_a", "only_a": 1}))
        f2 = tmp_path / "b.json"
        f2.write_text(json.dumps({"x": "from_b", "only_b": 2}))
        cfg = Config(file_paths=[str(f1), str(f2)], load_dotenv_file=False)
        assert cfg.x == "from_b"  # later wins
        assert cfg.only_a == 1
        assert cfg.only_b == 2

    def test_mixed_json_toml(self, tmp_path) -> None:
        j = tmp_path / "a.json"
        j.write_text(json.dumps({"x": 1, "y": 2}))
        t = tmp_path / "b.toml"
        t.write_text("x = 10\nz = 3\n")
        cfg = Config(file_paths=[str(j), str(t)], load_dotenv_file=False)
        assert cfg.x == 10  # toml wins
        assert cfg.y == 2
        assert cfg.z == 3


# =============================================================================
# Parse failures during multi-file loading
# =============================================================================


class TestMultiFileParseFailures:
    """When a file in ``file_paths`` can't be parsed, it must be skipped
    with a warning. The other files continue to load.
    """

    def test_namespaced_corrupt_file_skipped(self, tmp_path, caplog) -> None:
        """Lines 482-484: tuple form (namespaced) entry that fails to
        parse triggers the namespaced exception handler, not the
        non-namespaced one.
        """
        good = tmp_path / "good.toml"
        good.write_text("[ns1]\nx = 1\n")
        bad = tmp_path / "bad.toml"
        bad.write_text("[malformed\n")  # unterminated table header
        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            cfg = Config(
                file_paths=[(str(good), "ns1"), (str(bad), "ns2")],
                load_dotenv_file=False,
            )
        # ns1 is loaded:
        assert cfg.ns1.x == 1
        # ns2 didn't load (no exception, no entry):
        assert "ns2" not in cfg
        # And a warning explains why:
        assert any(
            "Failed to load config file" in r.message and "bad.toml" in r.message
            for r in caplog.records
        )

    def test_non_namespaced_corrupt_file_skipped(self, tmp_path, caplog) -> None:
        """Lines 516-517: plain (non-namespaced) entry that fails to
        parse triggers the non-namespaced exception handler.
        """
        good = tmp_path / "good.toml"
        good.write_text("[a]\nb = 1\n")
        bad = tmp_path / "bad.toml"
        bad.write_text("[malformed\nkey =")
        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            cfg = Config(
                file_paths=[str(good), str(bad)],
                load_dotenv_file=False,
            )
        # Good file loaded:
        assert cfg.a.b == 1
        # Warning emitted:
        assert any(
            "Failed to load" in r.message and "bad.toml" in r.message
            for r in caplog.records
        )

    def test_file_path_corrupt_still_raises(self, tmp_path) -> None:
        """The original ``file_path=...`` (not ``file_paths``) is treated
        as required: a parse failure on THAT file raises rather than
        being skipped. This is the documented backward-compat behavior.
        """
        bad = tmp_path / "bad.toml"
        bad.write_text("[malformed\n")
        with pytest.raises(RuntimeError):
            Config(file_path=str(bad), load_dotenv_file=False)


# =============================================================================
# Unsupported file extension
# =============================================================================


class TestUnsupportedExtension:
    """Line 842: ``file_path`` with neither .json nor .toml raises."""

    def test_yaml_extension_raises(self, tmp_path) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("a: 1\n")
        with pytest.raises(RuntimeError, match="(?i)unsupported"):
            Config(file_path=str(f), load_dotenv_file=False)

    def test_no_extension_raises(self, tmp_path) -> None:
        f = tmp_path / "config"
        f.write_text('{"a": 1}')
        with pytest.raises(RuntimeError, match="(?i)unsupported"):
            Config(file_path=str(f), load_dotenv_file=False)

    def test_yaml_in_file_paths_gets_skipped(self, tmp_path, caplog) -> None:
        """In ``file_paths`` (not ``file_path``), unsupported extensions
        should be a soft skip, not a raise (consistent with the warn-
        and-skip policy for other parse failures).
        """
        good = tmp_path / "good.json"
        good.write_text('{"a": 1}')
        yaml = tmp_path / "config.yaml"
        yaml.write_text("a: 1\n")
        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            cfg = Config(
                file_paths=[str(good), str(yaml)],
                load_dotenv_file=False,
            )
        assert cfg.a == 1


# =============================================================================
# TOML key promotion edges
# =============================================================================


class TestTomlKeyPromotion:
    """The TOML loader supports an optional "key promotion" step where
    keys inside ``[section]`` that match a root-level key in
    ``defaults`` are moved back to the root. The existing test_loader.py
    covers the happy path (a key that's only in a section). This class
    covers the two edges:
    """

    def test_already_at_root_warns_and_keeps_root_value(self, tmp_path, caplog) -> None:
        """Line 829: when a TOML key exists BOTH at root AND in a section,
        the root value wins and the in-section one is skipped with a
        warning.
        """
        f = tmp_path / "promo.toml"
        f.write_text('promoted = "at_root"\n\n[section]\npromoted = "in_section"\n')
        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            cfg = Config(
                defaults={"promoted": "default"},
                file_path=str(f),
                load_dotenv_file=False,
            )
        # Root-level value wins:
        assert cfg.promoted == "at_root"
        # The in-section copy is preserved at section.promoted:
        assert cfg.section.promoted == "in_section"
        # A warning explains the skipped promotion:
        assert any(
            "Skipping promotion" in r.message
            and "already exists at the root" in r.message
            for r in caplog.records
        )

    def test_empty_section_removed_after_promotion(self, tmp_path) -> None:
        """Lines 833-836: if a TOML section contains ONLY a promotable
        key, after the promotion the section becomes empty and is
        removed from the loaded data.
        """
        f = tmp_path / "empty.toml"
        f.write_text(
            '[section]\npromoted = "from_section"\n'
            # No other keys in this section.
        )
        cfg = Config(
            defaults={"promoted": "default"},
            file_path=str(f),
            load_dotenv_file=False,
        )
        # The key was promoted to the root:
        assert cfg.promoted == "from_section"
        # The (now-empty) section was removed:
        assert "section" not in cfg

    def test_non_empty_section_preserved_after_promotion(self, tmp_path) -> None:
        """A section with other keys survives promotion (just without
        the promoted key).
        """
        f = tmp_path / "partial.toml"
        f.write_text('[section]\npromoted = "from_section"\nother = "stays"\n')
        cfg = Config(
            defaults={"promoted": "default"},
            file_path=str(f),
            load_dotenv_file=False,
        )
        assert cfg.promoted == "from_section"
        assert cfg.section.other == "stays"
        # 'promoted' is NOT also under section after the move:
        assert "promoted" not in cfg.section

    def test_no_promotion_when_key_not_in_defaults(self, tmp_path) -> None:
        """If a TOML key doesn't match a root-level default, no
        promotion occurs (it stays in its section).
        """
        f = tmp_path / "no_promo.toml"
        f.write_text('[section]\nnot_in_defaults = "x"\n')
        cfg = Config(
            defaults={"different_key": "y"},
            file_path=str(f),
            load_dotenv_file=False,
        )
        assert cfg.section.not_in_defaults == "x"
        # Did NOT get promoted:
        assert "not_in_defaults" not in cfg

    def test_no_promotion_when_no_defaults(self, tmp_path) -> None:
        """No defaults supplied → no promotion logic fires at all."""
        f = tmp_path / "no_defaults.toml"
        f.write_text('[section]\nkey = "v"\n')
        cfg = Config(file_path=str(f), load_dotenv_file=False)
        assert cfg.section.key == "v"


# =============================================================================
# _load_single_file via Config.__init__ (namespaced path)
# =============================================================================


class TestLoadSingleFileViaConfig:
    """The namespaced path uses ``_load_single_file`` directly, which has
    different error semantics than ``_load_config_file`` (no TOML key
    promotion, raises RuntimeError on parse failure that the
    multi-file loop catches and converts to a warning).
    """

    def test_namespaced_json(self, tmp_path) -> None:
        f = tmp_path / "ns.json"
        f.write_text(json.dumps({"k": "v"}))
        cfg = Config(
            file_paths=[(str(f), "myapp")],
            load_dotenv_file=False,
        )
        assert cfg.myapp.k == "v"

    def test_namespaced_json_parse_error_skipped(self, tmp_path, caplog) -> None:
        """Line 732 chain: ``_load_single_file`` raises on bad JSON; the
        multi-file loop catches it.
        """
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json")
        good = tmp_path / "good.json"
        good.write_text('{"k": "v"}')
        with caplog.at_level(logging.WARNING, logger="confy.loader"):
            cfg = Config(
                file_paths=[(str(good), "good"), (str(bad), "bad")],
                load_dotenv_file=False,
            )
        # Good namespace loaded:
        assert cfg.good.k == "v"
        # Bad namespace skipped:
        assert "bad" not in cfg
        assert any(
            "Failed to load" in r.message and "bad.json" in r.message
            for r in caplog.records
        )
