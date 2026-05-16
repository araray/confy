# tests/argparse_integration/test_argparse_integration.py
"""Tests for :mod:`confy.argparse_integration`.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §6.2 — Library Integration
* ``confy/argparse_integration.py`` (49 lines, 2 functions)

What the module provides
------------------------
A thin convenience shim for scripts that want to piggy-back on
:mod:`argparse` for a confy-driven CLI without using the full Click
front-end.

* :func:`build_arg_parser` — returns an :class:`argparse.ArgumentParser`
  pre-populated with ``--config``, ``--prefix``, and ``--overrides``.
* :func:`load_config_from_args` — calls ``parse_known_args()``, parses
  the overrides string, and returns a fully-built :class:`Config`.

Test strategy
-------------
* :func:`build_arg_parser` is tested directly — verify the parser
  returned has the expected three options plus ``--help``.
* :func:`load_config_from_args` reads ``sys.argv``, so we use
  :func:`pytest.monkeypatch.setattr` to inject controlled argv before
  each call. The autouse ``_env_snapshot`` from the project conftest
  cleans up any env vars set during tests.
* Unknown args are silently dropped because the module uses
  ``parse_known_args()``, not ``parse_args()``. We pin that behavior.
* The overrides parser mirrors the CLI's but skips silently on
  malformed pairs (no warning printed, just skipped) — pinned here.
"""

from __future__ import annotations

import argparse
import json

import pytest

from confy.argparse_integration import build_arg_parser, load_config_from_args
from confy.exceptions import MissingMandatoryConfig
from confy.loader import Config

pytestmark = pytest.mark.unit


# =============================================================================
# build_arg_parser
# =============================================================================


class TestBuildArgParser:
    """Verify the parser shape and option declarations."""

    def test_returns_argument_parser(self) -> None:
        parser = build_arg_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_has_config_option(self) -> None:
        parser = build_arg_parser()
        option_strings = {tuple(a.option_strings) for a in parser._actions}
        assert ("--config",) in option_strings

    def test_has_prefix_option(self) -> None:
        parser = build_arg_parser()
        option_strings = {tuple(a.option_strings) for a in parser._actions}
        assert ("--prefix",) in option_strings

    def test_has_overrides_option(self) -> None:
        parser = build_arg_parser()
        option_strings = {tuple(a.option_strings) for a in parser._actions}
        assert ("--overrides",) in option_strings

    def test_help_text_describes_purpose(self) -> None:
        parser = build_arg_parser()
        help_text = parser.format_help()
        assert "confy" in help_text.lower() or "config" in help_text.lower()

    def test_can_parse_all_three(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(
            ["--config", "/tmp/x.json", "--prefix", "MYAPP", "--overrides", "k:1"]
        )
        assert args.config == "/tmp/x.json"
        assert args.prefix == "MYAPP"
        assert args.overrides == "k:1"

    def test_all_options_default_to_none(self) -> None:
        """When not specified, every option defaults to ``None``."""
        parser = build_arg_parser()
        args = parser.parse_args([])
        assert args.config is None
        assert args.prefix is None
        assert args.overrides is None

    def test_unknown_args_via_parse_known_args(self) -> None:
        """``build_arg_parser`` itself uses regular ``parse_args``, but
        the module's main consumer (:func:`load_config_from_args`) uses
        ``parse_known_args``. Verify the parser supports that mode too.
        """
        parser = build_arg_parser()
        args, extras = parser.parse_known_args(
            ["--config", "/tmp/x.json", "--unknown", "value", "positional"]
        )
        assert args.config == "/tmp/x.json"
        # Unknown args are returned in the extras list:
        assert "--unknown" in extras
        assert "value" in extras
        assert "positional" in extras


# =============================================================================
# load_config_from_args — basic
# =============================================================================


class TestLoadConfigFromArgsBasic:
    """The happy paths: argv → Config."""

    def test_empty_argv_returns_empty_config(self, monkeypatch) -> None:
        """No args, no defaults → empty Config (no crash)."""
        monkeypatch.setattr("sys.argv", ["prog"])
        cfg = load_config_from_args()
        assert isinstance(cfg, Config)
        assert len(cfg) == 0

    def test_with_defaults_arg(self, monkeypatch) -> None:
        """``defaults=...`` is passed through to :class:`Config`."""
        monkeypatch.setattr("sys.argv", ["prog"])
        cfg = load_config_from_args(defaults={"key": "default_value"})
        assert cfg.key == "default_value"

    def test_with_config_file(self, monkeypatch, tmp_path) -> None:
        cfg_file = tmp_path / "c.json"
        cfg_file.write_text(json.dumps({"k": "from_file"}))
        monkeypatch.setattr("sys.argv", ["prog", "--config", str(cfg_file)])
        cfg = load_config_from_args()
        assert cfg.k == "from_file"

    def test_with_prefix_env_vars(self, monkeypatch) -> None:
        monkeypatch.setenv("MYAPP_K", "from_env")
        monkeypatch.setattr("sys.argv", ["prog", "--prefix", "MYAPP"])
        cfg = load_config_from_args()
        assert cfg.k == "from_env"


# =============================================================================
# load_config_from_args — overrides parsing
# =============================================================================


class TestLoadConfigFromArgsOverrides:
    """The module's own ``--overrides`` parser is similar to the CLI's
    but quieter: malformed pairs are silently skipped (no warning).
    """

    def test_overrides_with_json_value(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--overrides", "k:42"])
        cfg = load_config_from_args()
        assert cfg.k == 42

    def test_overrides_with_string_value(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--overrides", 'k:"text"'])
        cfg = load_config_from_args()
        assert cfg.k == "text"

    def test_overrides_raw_string_fallback(self, monkeypatch) -> None:
        """Values that don't parse as JSON are kept as raw strings."""
        monkeypatch.setattr("sys.argv", ["prog", "--overrides", "k:not_json"])
        cfg = load_config_from_args()
        assert cfg.k == "not_json"

    def test_overrides_multiple_pairs(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--overrides", "a:1,b:2,c:3"])
        cfg = load_config_from_args()
        assert cfg.a == 1
        assert cfg.b == 2
        assert cfg.c == 3

    def test_overrides_dot_notation(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--overrides", 'db.host:"h"'])
        cfg = load_config_from_args()
        assert cfg.db.host == "h"

    def test_overrides_whitespace_stripped(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--overrides", "  k  :  42  "])
        cfg = load_config_from_args()
        assert cfg.k == 42

    def test_overrides_malformed_pair_warns_and_skips(self, monkeypatch) -> None:
        """A pair without a colon emits a :class:`UserWarning` and is
        skipped (I-07: parity with the Click CLI's yellow warning on
        stderr).
        """
        import warnings

        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--overrides", "good:1,bad_no_colon,also:2"],
        )
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            cfg = load_config_from_args()
        # The good pairs are still processed:
        assert cfg.good == 1
        assert cfg.also == 2
        # The bad pair is dropped (not present, no exception raised):
        assert "bad_no_colon" not in cfg
        # Exactly one warning fired, naming the offending pair:
        malformed = [
            w
            for w in captured
            if issubclass(w.category, UserWarning) and "bad_no_colon" in str(w.message)
        ]
        assert len(malformed) == 1
        # Message names the option and the format hint:
        assert "key:json_value" in str(malformed[0].message).lower() or (
            "format" in str(malformed[0].message).lower()
        )

    def test_overrides_empty_value_kept_as_empty_string(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--overrides", "k:"])
        cfg = load_config_from_args()
        # JSONDecodeError on '' falls back to raw '' (after strip):
        assert cfg.k == ""


# =============================================================================
# load_config_from_args — full chain
# =============================================================================


class TestLoadConfigFromArgsFullChain:
    """All four sources composed: defaults, file, env, overrides."""

    def test_precedence_overrides_beats_all(self, monkeypatch, tmp_path) -> None:
        cfg_file = tmp_path / "c.json"
        cfg_file.write_text(json.dumps({"k": "from_file"}))
        monkeypatch.setenv("MYAPP_K", "from_env")
        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "--config",
                str(cfg_file),
                "--prefix",
                "MYAPP",
                "--overrides",
                'k:"from_overrides"',
            ],
        )
        cfg = load_config_from_args(defaults={"k": "from_defaults"})
        # Overrides win:
        assert cfg.k == "from_overrides"

    def test_disjoint_keys_all_survive(self, monkeypatch, tmp_path) -> None:
        """Each source contributes a unique key; every one survives in
        the merged config.

        Post-I-05 the argparse helper passes ``env_remap_fallback="flat"``
        unconditionally, which makes the env-var path
        ``MYAPP_ENV_ONLY`` deterministically collapse to ``env_only``
        (no more dotenv-mode vs direct-env-mode ambiguity that
        previously forced this test to use single-segment env-var
        names to avoid the surprise).
        """
        cfg_file = tmp_path / "c.json"
        cfg_file.write_text(json.dumps({"fileonly": "f"}))
        # Multi-segment env-var name — the explicit "flat" fallback
        # guarantees the result is the underscore-joined leaf key:
        monkeypatch.setenv("MYAPP_ENV_ONLY", "e")
        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "--config",
                str(cfg_file),
                "--prefix",
                "MYAPP",
                "--overrides",
                'overrideonly:"o"',
            ],
        )
        cfg = load_config_from_args(defaults={"defaultonly": "d"})
        assert cfg.defaultonly == "d"
        assert cfg.fileonly == "f"
        # Flat fallback: ``MYAPP_ENV_ONLY`` → ``env_only`` (NOT
        # ``env.only`` as it would have been under the old auto-dotenv
        # rule).
        assert cfg.env_only == "e"
        assert cfg.overrideonly == "o"


# =============================================================================
# load_config_from_args — mandatory
# =============================================================================


class TestLoadConfigFromArgsMandatory:
    """``mandatory=[...]`` is passed through to :class:`Config` and
    raises :class:`MissingMandatoryConfig` if unmet.
    """

    def test_mandatory_satisfied_by_defaults(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog"])
        cfg = load_config_from_args(
            defaults={"required": "x"},
            mandatory=["required"],
        )
        assert cfg.required == "x"

    def test_mandatory_satisfied_by_overrides(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--overrides", 'required:"x"'])
        cfg = load_config_from_args(mandatory=["required"])
        assert cfg.required == "x"

    def test_mandatory_missing_raises(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog"])
        with pytest.raises(MissingMandatoryConfig) as exc:
            load_config_from_args(mandatory=["required.key"])
        assert "required.key" in exc.value.missing_keys


# =============================================================================
# Unknown args handling
# =============================================================================


class TestUnknownArgs:
    """``parse_known_args`` means extra args don't crash — important when
    embedding in scripts that have their own argparse args.
    """

    def test_extra_args_ignored(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "--my-script-arg",
                "value",
                "--prefix",
                "MYAPP",
                "positional",
            ],
        )
        # Should not raise even though --my-script-arg isn't declared:
        cfg = load_config_from_args()
        assert isinstance(cfg, Config)

    def test_positional_args_ignored(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "first_positional", "second"])
        cfg = load_config_from_args()
        assert isinstance(cfg, Config)
