# tests/v040/test_phase2_provenance.py
# tests/test_phase2_provenance.py
"""
Tests for Phase 2 — Provenance Tracking & Diagnostics.

Covers:
    - ProvenanceEntry and ProvenanceStore standalone behavior
    - Provenance wired into deep_merge()
    - Provenance wired through Config.__init__
    - cfg.provenance(), cfg.provenance_history(), cfg.provenance_dump()
    - Opt-in behavior (disabled by default)
"""


import pytest

from confy.loader import Config, deep_merge
from confy.provenance import ProvenanceEntry, ProvenanceStore

# ---------------------------------------------------------------------------
# ProvenanceEntry
# ---------------------------------------------------------------------------


class TestProvenanceEntry:
    """Tests for the ProvenanceEntry dataclass."""

    def test_frozen(self):
        """ProvenanceEntry is immutable."""
        entry = ProvenanceEntry(value=42, source="defaults", key="a.b")
        with pytest.raises(AttributeError):
            entry.value = 99  # type: ignore[misc]

    def test_repr(self):
        """repr shows key = value ← source."""
        entry = ProvenanceEntry(value=42, source="file:config.toml", key="db.port")
        r = repr(entry)
        assert "db.port" in r
        assert "42" in r
        assert "file:config.toml" in r

    def test_equality(self):
        """Two entries with same fields are equal."""
        a = ProvenanceEntry(value=1, source="s", key="k")
        b = ProvenanceEntry(value=1, source="s", key="k")
        assert a == b


# ---------------------------------------------------------------------------
# ProvenanceStore
# ---------------------------------------------------------------------------


class TestProvenanceStore:
    """Tests for the ProvenanceStore."""

    def test_record_and_get(self):
        """Record and retrieve a single entry."""
        store = ProvenanceStore()
        store.record("a.b", 42, "defaults")
        entry = store.get("a.b")
        assert entry is not None
        assert entry.value == 42
        assert entry.source == "defaults"

    def test_get_missing(self):
        """get() returns None for unrecorded keys."""
        store = ProvenanceStore()
        assert store.get("missing") is None

    def test_override_moves_to_history(self):
        """Overriding a key moves the previous entry to history."""
        store = ProvenanceStore()
        store.record("a", 1, "defaults")
        store.record("a", 2, "file:config.toml")

        # Current is the override
        assert store.get("a").value == 2
        assert store.get("a").source == "file:config.toml"

        # History contains both
        history = store.get_history("a")
        assert len(history) == 2
        assert history[0].value == 1
        assert history[0].source == "defaults"
        assert history[1].value == 2

    def test_triple_override(self):
        """Three successive overrides produce correct history."""
        store = ProvenanceStore()
        store.record("x", "a", "defaults")
        store.record("x", "b", "file")
        store.record("x", "c", "env")

        assert store.get("x").value == "c"
        history = store.get_history("x")
        assert len(history) == 3
        assert [e.value for e in history] == ["a", "b", "c"]

    def test_all_entries(self):
        """all_entries() returns current state of all keys."""
        store = ProvenanceStore()
        store.record("a", 1, "s1")
        store.record("b", 2, "s2")
        entries = store.all_entries()
        assert len(entries) == 2
        assert entries["a"].value == 1
        assert entries["b"].value == 2

    def test_sources_summary(self):
        """sources_summary() counts keys per source category."""
        store = ProvenanceStore()
        store.record("a", 1, "file:config.toml")
        store.record("b", 2, "file:override.toml")
        store.record("c", 3, "env:LLMCORE_*")
        store.record("d", 4, "defaults")

        summary = store.sources_summary()
        assert summary["file"] == 2
        assert summary["env"] == 1
        assert summary["defaults"] == 1

    def test_get_history_empty(self):
        """get_history() returns empty list for unknown keys."""
        store = ProvenanceStore()
        assert store.get_history("unknown") == []


# ---------------------------------------------------------------------------
# deep_merge + provenance
# ---------------------------------------------------------------------------


class TestDeepMergeProvenance:
    """Tests for provenance recording in deep_merge()."""

    def test_provenance_records_leaf_values(self):
        """Leaf value overrides are recorded in provenance."""
        store = ProvenanceStore()
        base = {"a": 1, "b": {"c": 2}}
        updates = {"a": 10, "b": {"d": 3}}

        deep_merge(base, updates, _source="test", _provenance=store)

        assert store.get("a") is not None
        assert store.get("a").value == 10
        assert store.get("a").source == "test"

        assert store.get("b.d") is not None
        assert store.get("b.d").value == 3

    def test_provenance_not_recorded_for_dicts(self):
        """Dict-to-dict merges don't record the dict itself, only leaf values."""
        store = ProvenanceStore()
        base = {"a": {"b": 1}}
        updates = {"a": {"c": 2}}

        deep_merge(base, updates, _source="test", _provenance=store)

        # "a" should not be recorded (it's a dict merge, not an overwrite)
        assert store.get("a") is None
        # "a.c" should be recorded (leaf)
        assert store.get("a.c") is not None
        assert store.get("a.c").value == 2

    def test_provenance_tracks_override_chain(self):
        """Sequential merges build override history."""
        store = ProvenanceStore()
        base = {"x": 1}
        step1 = {"x": 2}
        step2 = {"x": 3}

        result = deep_merge(base, step1, _source="file", _provenance=store)
        result = deep_merge(result, step2, _source="env", _provenance=store)

        history = store.get_history("x")
        assert len(history) == 2
        assert history[0].source == "file"
        assert history[1].source == "env"

    def test_provenance_none_disables_tracking(self):
        """When _provenance is None, no recording happens (default)."""
        base = {"a": 1}
        updates = {"a": 2}
        # No error; just no tracking
        result = deep_merge(base, updates, _source="test", _provenance=None)
        assert result == {"a": 2}


# ---------------------------------------------------------------------------
# Config + provenance
# ---------------------------------------------------------------------------


class TestConfigProvenance:
    """Tests for provenance tracking through Config.__init__."""

    def test_disabled_by_default(self):
        """Provenance is off by default."""
        cfg = Config(defaults={"a": 1}, load_dotenv_file=False)
        assert cfg.provenance("a") is None
        assert cfg.provenance_history("a") == []
        assert cfg.provenance_dump() == {}

    def test_enabled_tracks_defaults(self):
        """When enabled, app_defaults are tracked."""
        cfg = Config(
            app_defaults={"myapp": {"port": 8080}},
            track_provenance=True,
            load_dotenv_file=False,
        )
        p = cfg.provenance("myapp.port")
        assert p is not None
        assert p.value == 8080
        assert "app_defaults" in p.source

    def test_file_overrides_tracked(self, tmp_path):
        """File values overriding defaults are tracked."""
        f = tmp_path / "config.toml"
        f.write_text("[myapp]\nport = 9090\n")

        cfg = Config(
            app_defaults={"myapp": {"port": 8080}},
            file_path=str(f),
            track_provenance=True,
            load_dotenv_file=False,
        )

        p = cfg.provenance("myapp.port")
        assert p is not None
        assert p.value == 9090
        assert "file:" in p.source

        # History should show default → file
        history = cfg.provenance_history("myapp.port")
        assert len(history) >= 2

    def test_env_overrides_tracked(self, monkeypatch):
        """Environment variable overrides are tracked."""
        monkeypatch.setenv("SEMANTISCAN_PORT", "7070")

        cfg = Config(
            app_defaults={"semantiscan": {"port": 8080}},
            app_prefixes={"semantiscan": "SEMANTISCAN"},
            track_provenance=True,
            load_dotenv_file=False,
        )

        p = cfg.provenance("semantiscan.port")
        assert p is not None
        assert p.value == 7070
        assert "env:" in p.source

    def test_overrides_dict_tracked(self):
        """overrides_dict values are tracked."""
        cfg = Config(
            app_defaults={"myapp": {"port": 8080}},
            overrides_dict={"myapp.port": "9999"},
            track_provenance=True,
            load_dotenv_file=False,
        )

        p = cfg.provenance("myapp.port")
        assert p is not None
        assert p.value == 9999
        assert "overrides_dict" in p.source

    def test_provenance_dump(self):
        """provenance_dump() returns {key: source} dict."""
        cfg = Config(
            app_defaults={"myapp": {"a": 1, "b": 2}},
            track_provenance=True,
            load_dotenv_file=False,
        )
        dump = cfg.provenance_dump()
        assert isinstance(dump, dict)
        assert "myapp.a" in dump
        assert "myapp.b" in dump
        assert "app_defaults" in dump["myapp.a"]

    def test_provenance_dump_empty_when_disabled(self):
        """provenance_dump() returns {} when tracking disabled."""
        cfg = Config(defaults={"a": 1}, load_dotenv_file=False)
        assert cfg.provenance_dump() == {}
