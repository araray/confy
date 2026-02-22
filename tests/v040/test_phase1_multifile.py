# tests/v040/test_phase1_multifile.py
# tests/test_phase1_multifile.py
"""
Tests for Phase 1 — Multi-File & App Collections.

Covers:
    - file_paths: loading multiple config files in order
    - Namespaced files via tuple form (path, namespace)
    - app_defaults: per-app default configs
    - app(): namespace accessor
    - app_prefixes: per-app environment variable routing
    - _apply_namespace: auto-detection of existing namespace keys
"""

import json

import pytest

from confy.loader import Config

# ---------------------------------------------------------------------------
# Multi-File Loading
# ---------------------------------------------------------------------------


class TestMultiFile:
    """Tests for the file_paths parameter."""

    def test_file_paths_basic(self, tmp_path):
        """Multiple files merged left-to-right (later wins)."""
        f1 = tmp_path / "base.toml"
        f1.write_text('[db]\nhost = "localhost"\nport = 5432\n')
        f2 = tmp_path / "override.toml"
        f2.write_text('[db]\nhost = "prod.example.com"\n')

        cfg = Config(file_paths=[str(f1), str(f2)], load_dotenv_file=False)
        assert cfg.db.host == "prod.example.com"
        assert cfg.db.port == 5432  # Not in f2, so from f1

    def test_file_path_and_file_paths_combined(self, tmp_path):
        """file_path is prepended to file_paths."""
        f1 = tmp_path / "first.toml"
        f1.write_text("[x]\na = 1\n")
        f2 = tmp_path / "second.toml"
        f2.write_text("[x]\na = 2\nb = 3\n")

        cfg = Config(
            file_path=str(f1),
            file_paths=[str(f2)],
            load_dotenv_file=False,
        )
        assert cfg.x.a == 2  # f2 overrides f1
        assert cfg.x.b == 3  # f2 adds new key

    def test_namespaced_file(self, tmp_path):
        """Tuple form (path, namespace) nests file under namespace."""
        f = tmp_path / "scan.toml"
        f.write_text("[chunking]\nchunk_size = 2000\n")

        cfg = Config(
            file_paths=[(str(f), "semantiscan")],
            load_dotenv_file=False,
        )
        assert cfg.semantiscan.chunking.chunk_size == 2000

    def test_namespace_auto_detection(self, tmp_path):
        """File already containing namespace key — don't double-nest."""
        f = tmp_path / "scan.toml"
        f.write_text(
            "[semantiscan]\nenabled = true\n\n"
            "[semantiscan.chunking]\nchunk_size = 2000\n"
        )

        cfg = Config(
            file_paths=[(str(f), "semantiscan")],
            load_dotenv_file=False,
        )
        assert cfg.semantiscan.chunking.chunk_size == 2000
        assert cfg.semantiscan.enabled is True
        # No double nesting:
        assert not hasattr(cfg.semantiscan, "semantiscan")

    def test_namespace_pyproject_style(self, tmp_path):
        """pyproject.toml-style [tool.namespace] nesting is detected."""
        f = tmp_path / "pyproject.toml"
        f.write_text(
            '[tool.myapp]\nversion = "1.0"\n\n[tool.myapp.db]\nhost = "localhost"\n'
        )

        cfg = Config(
            file_paths=[(str(f), "myapp")],
            load_dotenv_file=False,
        )
        assert cfg.myapp.version == "1.0"
        assert cfg.myapp.db.host == "localhost"

    def test_missing_file_skipped_with_warning(self, tmp_path, caplog):
        """Non-existent namespaced files are skipped, not errors."""
        cfg = Config(
            file_paths=[(str(tmp_path / "nonexistent.toml"), "myapp")],
            load_dotenv_file=False,
        )
        assert "nonexistent" in caplog.text.lower() or len(cfg) == 0

    def test_missing_non_namespaced_extra_file_skipped(self, tmp_path, caplog):
        """Non-existent extra files in file_paths are skipped gracefully."""
        f1 = tmp_path / "exists.toml"
        f1.write_text('[db]\nhost = "localhost"\n')

        # The non-existent file is a second entry in file_paths (not file_path)
        cfg = Config(
            file_paths=[str(f1), str(tmp_path / "missing.toml")],
            load_dotenv_file=False,
        )
        assert cfg.db.host == "localhost"

    def test_original_file_path_still_raises_on_missing(self, tmp_path):
        """Original file_path parameter still raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            Config(
                file_path=str(tmp_path / "nonexistent.toml"),
                load_dotenv_file=False,
            )

    def test_mixed_json_and_toml(self, tmp_path):
        """Can mix JSON and TOML files in file_paths."""
        f1 = tmp_path / "base.json"
        f1.write_text(json.dumps({"a": 1, "b": 2}))
        f2 = tmp_path / "override.toml"
        f2.write_text("a = 10\nc = 30\n")

        cfg = Config(
            file_paths=[str(f1), str(f2)],
            load_dotenv_file=False,
        )
        assert cfg.a == 10  # TOML overrides JSON
        assert cfg.b == 2  # Preserved from JSON
        assert cfg.c == 30  # New from TOML

    def test_three_files_cascading(self, tmp_path):
        """Three-level cascade: defaults → base → user → local."""
        base = tmp_path / "base.toml"
        base.write_text('[db]\nhost = "base"\nport = 5432\ntimeout = 30\n')
        user = tmp_path / "user.toml"
        user.write_text('[db]\nhost = "user"\nport = 5433\n')
        local = tmp_path / "local.toml"
        local.write_text('[db]\nhost = "local"\n')

        cfg = Config(
            file_paths=[str(base), str(user), str(local)],
            load_dotenv_file=False,
        )
        assert cfg.db.host == "local"  # local wins
        assert cfg.db.port == 5433  # user wins (local doesn't have it)
        assert cfg.db.timeout == 30  # base preserved


# ---------------------------------------------------------------------------
# App Defaults
# ---------------------------------------------------------------------------


class TestAppDefaults:
    """Tests for the app_defaults parameter."""

    def test_app_defaults_basic(self):
        """app_defaults creates namespaced defaults."""
        cfg = Config(
            app_defaults={
                "myapp": {"debug": True, "port": 8080},
            },
            load_dotenv_file=False,
        )
        assert cfg.myapp.debug is True
        assert cfg.myapp.port == 8080

    def test_app_defaults_overridden_by_file(self, tmp_path):
        """File values override app_defaults."""
        f = tmp_path / "config.toml"
        f.write_text("[myapp]\ndebug = false\n")

        cfg = Config(
            app_defaults={"myapp": {"debug": True, "port": 8080}},
            file_path=str(f),
            load_dotenv_file=False,
        )
        assert cfg.myapp.debug is False  # File wins
        assert cfg.myapp.port == 8080  # Default preserved

    def test_app_defaults_and_regular_defaults_coexist(self):
        """app_defaults and defaults both contribute."""
        cfg = Config(
            defaults={"shared_key": "shared_value"},
            app_defaults={"myapp": {"app_key": "app_value"}},
            load_dotenv_file=False,
        )
        assert cfg.shared_key == "shared_value"
        assert cfg.myapp.app_key == "app_value"

    def test_defaults_override_app_defaults(self):
        """If defaults has same app namespace key, defaults wins."""
        cfg = Config(
            defaults={"myapp": {"port": 9090}},
            app_defaults={"myapp": {"port": 8080, "debug": True}},
            load_dotenv_file=False,
        )
        assert cfg.myapp.port == 9090  # defaults wins
        assert cfg.myapp.debug is True  # app_defaults preserved where no conflict

    def test_multiple_apps(self):
        """Multiple app namespaces coexist."""
        cfg = Config(
            app_defaults={
                "llmcore": {"provider": "openai", "timeout": 60},
                "semantiscan": {"chunk_size": 1500, "top_k": 10},
            },
            load_dotenv_file=False,
        )
        assert cfg.llmcore.provider == "openai"
        assert cfg.llmcore.timeout == 60
        assert cfg.semantiscan.chunk_size == 1500
        assert cfg.semantiscan.top_k == 10

    def test_app_defaults_overridden_by_namespaced_file(self, tmp_path):
        """Namespaced file overrides app_defaults."""
        f = tmp_path / "scan_config.toml"
        f.write_text("[chunking]\nchunk_size = 3000\n")

        cfg = Config(
            app_defaults={
                "semantiscan": {"chunking": {"chunk_size": 1500, "overlap": 200}},
            },
            file_paths=[(str(f), "semantiscan")],
            load_dotenv_file=False,
        )
        assert cfg.semantiscan.chunking.chunk_size == 3000  # File wins
        assert cfg.semantiscan.chunking.overlap == 200  # Default preserved


# ---------------------------------------------------------------------------
# App Accessor
# ---------------------------------------------------------------------------


class TestAppAccessor:
    """Tests for the cfg.app() method."""

    def test_app_returns_config(self):
        """app() returns a Config object for existing namespace."""
        cfg = Config(
            app_defaults={"myapp": {"key": "val"}},
            load_dotenv_file=False,
        )
        sub = cfg.app("myapp")
        assert isinstance(sub, Config)
        assert sub.key == "val"

    def test_app_missing_returns_empty_config(self):
        """app() on missing namespace returns empty Config."""
        cfg = Config(load_dotenv_file=False)
        sub = cfg.app("nonexistent")
        assert isinstance(sub, Config)
        assert len(sub) == 0

    def test_app_and_dot_notation_equivalent(self):
        """app() and direct attribute access yield same result."""
        cfg = Config(
            app_defaults={"myapp": {"nested": {"deep": 42}}},
            load_dotenv_file=False,
        )
        assert cfg.app("myapp").nested.deep == cfg.myapp.nested.deep == 42

    def test_app_wraps_raw_dict(self):
        """app() wraps a raw dict sub-key into Config."""
        cfg = Config({"myapp": {"key": "val"}}, load_dotenv_file=False)
        sub = cfg.app("myapp")
        assert isinstance(sub, Config)
        assert sub.key == "val"

    def test_app_idempotent(self):
        """Calling app() twice returns the same object."""
        cfg = Config(
            app_defaults={"myapp": {"x": 1}},
            load_dotenv_file=False,
        )
        sub1 = cfg.app("myapp")
        sub2 = cfg.app("myapp")
        assert sub1 is sub2


# ---------------------------------------------------------------------------
# App Prefixes
# ---------------------------------------------------------------------------


class TestAppPrefixes:
    """Tests for per-app environment variable routing."""

    def test_app_prefix_routes_env_vars(self, monkeypatch):
        """SEMANTISCAN_* env vars route to cfg.semantiscan.*"""
        monkeypatch.setenv("SEMANTISCAN_CHUNKING__CHUNK_SIZE", "3000")

        cfg = Config(
            app_defaults={"semantiscan": {"chunking": {"chunk_size": 1500}}},
            app_prefixes={"semantiscan": "SEMANTISCAN"},
            load_dotenv_file=False,
        )
        assert cfg.semantiscan.chunking.chunk_size == 3000

    def test_app_prefix_does_not_affect_other_namespaces(self, monkeypatch):
        """App-prefix env vars don't bleed into other namespaces."""
        monkeypatch.setenv("SEMANTISCAN_ENABLED", "true")

        cfg = Config(
            app_defaults={
                "semantiscan": {"enabled": False},
                "llmcore": {"provider": "openai"},
            },
            app_prefixes={"semantiscan": "SEMANTISCAN"},
            load_dotenv_file=False,
        )
        assert cfg.semantiscan.enabled is True
        assert cfg.llmcore.provider == "openai"

    def test_overrides_dict_wins_over_app_prefix(self, monkeypatch):
        """overrides_dict has highest precedence, even above app prefix env."""
        monkeypatch.setenv("SEMANTISCAN_ENABLED", "true")

        cfg = Config(
            app_defaults={"semantiscan": {"enabled": False}},
            app_prefixes={"semantiscan": "SEMANTISCAN"},
            overrides_dict={"semantiscan.enabled": "false"},
            load_dotenv_file=False,
        )
        assert cfg.semantiscan.enabled is False  # override wins


# ---------------------------------------------------------------------------
# _apply_namespace
# ---------------------------------------------------------------------------


class TestApplyNamespace:
    """Tests for Config._apply_namespace() static method."""

    def test_nests_data(self):
        """Plain data is nested under namespace."""
        result = Config._apply_namespace({"chunking": {"size": 100}}, "semantiscan")
        assert result == {"semantiscan": {"chunking": {"size": 100}}}

    def test_extracts_existing_namespace(self):
        """File already has namespace key — extracts, doesn't double-nest."""
        result = Config._apply_namespace(
            {"semantiscan": {"a": 1}, "other": "val"}, "semantiscan"
        )
        assert result == {"semantiscan": {"a": 1}}

    def test_extracts_pyproject_tool(self):
        """pyproject.toml [tool.X] pattern is detected."""
        result = Config._apply_namespace(
            {"tool": {"myapp": {"version": "1.0"}}, "build": "setup"}, "myapp"
        )
        assert result == {"myapp": {"version": "1.0"}}

    def test_no_tool_key_nests(self):
        """When tool key exists but doesn't have namespace, regular nesting."""
        result = Config._apply_namespace(
            {"tool": {"other": "val"}, "key": "value"}, "myapp"
        )
        assert result == {"myapp": {"tool": {"other": "val"}, "key": "value"}}

    def test_empty_dict(self):
        """Empty dict is wrapped."""
        result = Config._apply_namespace({}, "app")
        assert result == {"app": {}}
