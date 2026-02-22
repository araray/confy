# tests/v040/test_phase0_foundation.py
# tests/test_phase0_foundation.py
"""
Tests for Phase 0 — Foundation Enhancements.

Covers:
    - Config._load_single_file() — pure file→dict loading
    - deep_merge() backward compat with new _source/_provenance params
    - confy.utils — expand_path(), resolve_path()
"""

import json

import pytest

from confy.loader import Config, deep_merge
from confy.utils import expand_path, resolve_path

# ---------------------------------------------------------------------------
# _load_single_file
# ---------------------------------------------------------------------------


class TestLoadSingleFile:
    """Tests for the new _load_single_file() static method."""

    def test_load_json(self, tmp_path):
        """Load a valid JSON file."""
        f = tmp_path / "test.json"
        f.write_text(json.dumps({"a": 1, "b": {"c": 2}}))
        result = Config._load_single_file(str(f))
        assert result == {"a": 1, "b": {"c": 2}}

    def test_load_toml(self, tmp_path):
        """Load a valid TOML file."""
        f = tmp_path / "test.toml"
        f.write_text('[section]\nkey = "value"\n')
        result = Config._load_single_file(str(f))
        assert result == {"section": {"key": "value"}}

    def test_load_toml_nested(self, tmp_path):
        """Load a TOML file with nested sections — no key promotion."""
        f = tmp_path / "nested.toml"
        f.write_text(
            '[app]\nname = "myapp"\n\n[app.db]\nhost = "localhost"\nport = 5432\n'
        )
        result = Config._load_single_file(str(f))
        assert result == {
            "app": {
                "name": "myapp",
                "db": {"host": "localhost", "port": 5432},
            }
        }

    def test_file_not_found(self):
        """Non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            Config._load_single_file("/nonexistent/path.toml")

    def test_invalid_json(self, tmp_path):
        """Malformed JSON raises RuntimeError."""
        f = tmp_path / "bad.json"
        f.write_text("{invalid json")
        with pytest.raises((RuntimeError, json.JSONDecodeError)):
            Config._load_single_file(str(f))

    def test_invalid_toml(self, tmp_path):
        """Malformed TOML raises RuntimeError."""
        f = tmp_path / "bad.toml"
        f.write_text('[section\nkey = "broken')
        with pytest.raises(RuntimeError):
            Config._load_single_file(str(f))

    def test_unsupported_format(self, tmp_path):
        """Unsupported file extension raises RuntimeError."""
        f = tmp_path / "test.yaml"
        f.write_text("key: value")
        with pytest.raises(RuntimeError, match="Unsupported"):
            Config._load_single_file(str(f))

    def test_expands_user_path(self, tmp_path, monkeypatch):
        """Tilde expansion is applied to file paths."""
        monkeypatch.setenv("HOME", str(tmp_path))
        f = tmp_path / "config.json"
        f.write_text('{"x": 1}')
        result = Config._load_single_file("~/config.json")
        assert result == {"x": 1}

    def test_expands_env_var_path(self, tmp_path, monkeypatch):
        """Environment variables in paths are expanded."""
        monkeypatch.setenv("TEST_CONFIG_DIR", str(tmp_path))
        f = tmp_path / "config.json"
        f.write_text('{"y": 2}')
        result = Config._load_single_file("$TEST_CONFIG_DIR/config.json")
        assert result == {"y": 2}

    def test_empty_json(self, tmp_path):
        """Empty JSON object returns empty dict."""
        f = tmp_path / "empty.json"
        f.write_text("{}")
        result = Config._load_single_file(str(f))
        assert result == {}

    def test_empty_toml(self, tmp_path):
        """Empty TOML file returns empty dict."""
        f = tmp_path / "empty.toml"
        f.write_text("")
        result = Config._load_single_file(str(f))
        assert result == {}


# ---------------------------------------------------------------------------
# deep_merge backward compat
# ---------------------------------------------------------------------------


class TestDeepMergeSourceParam:
    """Verify deep_merge still works identically with new optional params."""

    def test_backward_compat_no_source(self):
        """Calling without new params is identical to old behavior."""
        base = {"a": 1, "b": {"c": 2}}
        updates = {"b": {"d": 3}, "e": 4}
        result = deep_merge(base, updates)
        assert result == {"a": 1, "b": {"c": 2, "d": 3}, "e": 4}

    def test_with_source_param_ignored(self):
        """_source param doesn't change merge behavior when _provenance is None."""
        base = {"a": 1}
        updates = {"a": 2}
        result = deep_merge(base, updates, _source="test_file.toml")
        assert result == {"a": 2}

    def test_with_provenance_param_ignored_when_none(self):
        """_provenance=None means no tracking (default)."""
        base = {"a": 1}
        updates = {"a": 2}
        result = deep_merge(base, updates, _source="test", _provenance=None)
        assert result == {"a": 2}

    def test_does_not_mutate_base(self):
        """Original base dict is not modified."""
        base = {"a": {"b": 1}}
        updates = {"a": {"c": 2}}
        result = deep_merge(base, updates)
        assert result == {"a": {"b": 1, "c": 2}}
        assert base == {"a": {"b": 1}}  # Unchanged

    def test_does_not_mutate_updates(self):
        """Original updates dict is not modified."""
        base = {"a": 1}
        updates = {"a": {"nested": True}}
        original_updates = {"a": {"nested": True}}
        deep_merge(base, updates)
        assert updates == original_updates

    def test_list_overwrite(self):
        """Lists in updates replace lists in base (no merging)."""
        base = {"items": [1, 2, 3]}
        updates = {"items": [4, 5]}
        result = deep_merge(base, updates)
        assert result == {"items": [4, 5]}

    def test_config_object_preserved(self):
        """Config objects in updates are preserved (not deep-copied)."""
        base = {"a": 1}
        cfg = Config({"nested": True})
        updates = {"a": cfg}
        result = deep_merge(base, updates)
        assert result["a"] is cfg


# ---------------------------------------------------------------------------
# expand_path / resolve_path
# ---------------------------------------------------------------------------


class TestExpandPath:
    """Tests for confy.utils.expand_path()."""

    def test_none_input(self):
        assert expand_path(None) is None

    def test_tilde_expansion(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/testuser")
        result = expand_path("~/configs/app.toml")
        assert result == "/home/testuser/configs/app.toml"

    def test_env_var_expansion(self, monkeypatch):
        monkeypatch.setenv("MY_DIR", "/opt/config")
        result = expand_path("$MY_DIR/app.toml")
        assert result == "/opt/config/app.toml"

    def test_plain_path_unchanged(self):
        result = expand_path("/absolute/path/config.toml")
        assert result == "/absolute/path/config.toml"


class TestResolvePath:
    """Tests for confy.utils.resolve_path()."""

    def test_none_input(self):
        assert resolve_path(None) is None

    def test_returns_path_object(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        from pathlib import Path

        result = resolve_path("~/test")
        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_resolves_relative(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from pathlib import Path

        result = resolve_path("relative/path")
        assert isinstance(result, Path)
        assert result.is_absolute()
        assert str(tmp_path) in str(result)
