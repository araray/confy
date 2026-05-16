# tests/integration/test_round_trip.py
"""Integration tests for round-trip data fidelity.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §5.2 (Config Object), §5.3.4 (Files)
* ``confy/loader.py`` :meth:`Config.as_dict` lines 1301-1314

What this file tests
--------------------
The conversion paths between :class:`Config`, plain ``dict``, and files
on disk should be *information-preserving*: data that enters and exits
must compare equal, and repeated conversions must stabilize.

* **Config → as_dict → Config**: passing a Config's dict form through
  the constructor must reproduce an equal config.
* **Config → JSON → Config**: writing a config to JSON and re-loading
  must round-trip cleanly.
* **Config → TOML → Config**: same, with TOML format.
* **as_dict idempotency**: calling ``as_dict`` twice yields equal
  results; the second call doesn't accumulate Configs.
* **__str__ produces parseable JSON**: not just decorative — the
  output should be machine-readable.
"""

from __future__ import annotations

import json

import pytest
import tomli
import tomli_w

from confy.loader import Config

pytestmark = pytest.mark.integration


# =============================================================================
# Config → as_dict → Config
# =============================================================================


class TestAsDictRoundTrip:
    """A Config converted to dict and back must produce an equal Config."""

    def test_flat_round_trip(self) -> None:
        original = Config(a=1, b="x", c=True, load_dotenv_file=False)
        plain = original.as_dict()
        reconstructed = Config(defaults=plain, load_dotenv_file=False)
        assert reconstructed.as_dict() == original.as_dict()

    def test_nested_round_trip(self) -> None:
        original = Config(
            defaults={
                "db": {"host": "h", "port": 5432, "opts": {"deep": True}},
                "logging": {"level": "INFO"},
                "list_data": [1, {"a": 2}, "x"],
            },
            load_dotenv_file=False,
        )
        plain = original.as_dict()
        reconstructed = Config(defaults=plain, load_dotenv_file=False)
        assert reconstructed.as_dict() == original.as_dict()

    def test_round_trip_with_all_sources(self, tmp_path, monkeypatch) -> None:
        """A multi-source config also round-trips."""
        f = tmp_path / "c.json"
        f.write_text(json.dumps({"file_key": "f"}))
        monkeypatch.setenv("MYAPP_ENV_KEY", "e")
        original = Config(
            defaults={"def_key": "d"},
            file_path=str(f),
            prefix="MYAPP",
            overrides_dict={"ovr_key": "o"},
            load_dotenv_file=False,
        )
        plain = original.as_dict()
        reconstructed = Config(defaults=plain, load_dotenv_file=False)
        assert reconstructed.as_dict() == original.as_dict()


# =============================================================================
# Config → JSON file → Config
# =============================================================================


class TestJsonFileRoundTrip:
    """Write a Config as JSON, re-read into a new Config, compare."""

    def test_simple(self, tmp_path) -> None:
        original = Config(
            defaults={
                "a": 1,
                "b": "x",
                "c": True,
                "n": None,
                "list_data": [1, 2, 3],
            },
            load_dotenv_file=False,
        )
        f = tmp_path / "out.json"
        f.write_text(json.dumps(original.as_dict()))
        loaded = Config(file_path=str(f), load_dotenv_file=False)
        assert loaded.as_dict() == original.as_dict()

    def test_nested(self, tmp_path) -> None:
        original = Config(
            defaults={"db": {"host": "h", "creds": {"u": "user", "p": "pass"}}},
            load_dotenv_file=False,
        )
        f = tmp_path / "out.json"
        f.write_text(json.dumps(original.as_dict()))
        loaded = Config(file_path=str(f), load_dotenv_file=False)
        assert loaded.db.host == "h"
        assert loaded.db.creds.u == "user"
        assert loaded.as_dict() == original.as_dict()


# =============================================================================
# Config → TOML file → Config
# =============================================================================


class TestTomlFileRoundTrip:
    """TOML round-trip via tomli_w.

    Note: TOML doesn't have a ``null`` type, so we exclude None values
    from this test. The library doesn't pretend to handle None in TOML.
    """

    def test_scalars_and_nested(self, tmp_path) -> None:
        original = Config(
            defaults={
                "a": 1,
                "b": "x",
                "c": True,
                "db": {"host": "h", "port": 5432},
            },
            load_dotenv_file=False,
        )
        f = tmp_path / "out.toml"
        with open(f, "wb") as fh:
            tomli_w.dump(original.as_dict(), fh)
        loaded = Config(file_path=str(f), load_dotenv_file=False)
        assert loaded.as_dict() == original.as_dict()

    def test_list_of_dicts(self, tmp_path) -> None:
        """TOML inline tables (or [[arrays of tables]]) round-trip too."""
        original = Config(
            defaults={"my_records": [{"a": 1}, {"a": 2}]},
            load_dotenv_file=False,
        )
        f = tmp_path / "out.toml"
        with open(f, "wb") as fh:
            tomli_w.dump(original.as_dict(), fh)
        loaded = Config(file_path=str(f), load_dotenv_file=False)
        # Verify the list survived the round trip:
        assert len(loaded.my_records) == 2
        assert loaded.my_records[0].a == 1
        assert loaded.my_records[1].a == 2


# =============================================================================
# as_dict idempotency
# =============================================================================


class TestAsDictIdempotency:
    """Repeated ``as_dict`` calls must produce equal results."""

    def test_twice_equal(self) -> None:
        cfg = Config(
            defaults={"db": {"host": "h", "port": 5432}},
            load_dotenv_file=False,
        )
        d1 = cfg.as_dict()
        d2 = cfg.as_dict()
        assert d1 == d2
        # And they're independent objects:
        assert d1 is not d2

    def test_no_config_objects_leak(self) -> None:
        """The result of ``as_dict`` should contain ONLY plain dicts,
        lists, and primitives — no Config instances anywhere."""
        cfg = Config(
            defaults={
                "a": {"b": {"c": 1}},
                "items": [{"nested": {"deep": "v"}}],
            },
            load_dotenv_file=False,
        )
        d = cfg.as_dict()

        def assert_no_config(obj, path="root"):
            if isinstance(obj, dict):
                assert type(obj) is dict, f"Config at {path}: {type(obj)}"
                for k, v in obj.items():
                    assert_no_config(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    assert_no_config(item, f"{path}[{i}]")

        assert_no_config(d)

    def test_mutating_result_does_not_affect_source(self) -> None:
        cfg = Config(defaults={"db": {"host": "h"}}, load_dotenv_file=False)
        d = cfg.as_dict()
        d["db"]["host"] = "MUTATED"
        # cfg unchanged:
        assert cfg.db.host == "h"


# =============================================================================
# __str__ output is valid JSON
# =============================================================================


class TestStrIsValidJson:
    """``str(cfg)`` returns ``json.dumps(self.as_dict(), indent=2)`` when
    serialization succeeds. The output must be machine-readable.
    """

    def test_simple_str_parses_back(self) -> None:
        cfg = Config(
            defaults={"a": 1, "b": "x", "c": True},
            load_dotenv_file=False,
        )
        s = str(cfg)
        parsed = json.loads(s)
        assert parsed == cfg.as_dict()

    def test_nested_str_parses_back(self) -> None:
        cfg = Config(
            defaults={"db": {"host": "h", "port": 5432}},
            load_dotenv_file=False,
        )
        parsed = json.loads(str(cfg))
        assert parsed == cfg.as_dict()


# =============================================================================
# Cross-format conversion: JSON → Config → TOML → Config
# =============================================================================


class TestCrossFormatConversion:
    """Load from JSON, save as TOML, re-load — data should equal the
    original (within TOML's type constraints).
    """

    def test_json_to_toml_to_config(self, tmp_path) -> None:
        # Step 1: write source JSON
        source = {"a": 1, "b": "x", "db": {"host": "h", "port": 5432}}
        src = tmp_path / "src.json"
        src.write_text(json.dumps(source))

        # Step 2: load it
        cfg1 = Config(file_path=str(src), load_dotenv_file=False)
        assert cfg1.as_dict() == source

        # Step 3: write back as TOML
        out = tmp_path / "out.toml"
        with open(out, "wb") as f:
            tomli_w.dump(cfg1.as_dict(), f)

        # Step 4: re-load from TOML
        cfg2 = Config(file_path=str(out), load_dotenv_file=False)
        assert cfg2.as_dict() == source
