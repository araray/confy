# confy/provenance.py
"""
confy.provenance
----------------

Optional provenance tracking for configuration values.

When enabled via ``Config(track_provenance=True)``, every ``deep_merge()``
call records which source set each key's final value. This enables
debugging "why is this value X?" by tracing the merge chain.

Thread-safety:
    - ``ProvenanceStore`` writes only during ``Config.__init__`` (single-threaded).
    - Reads (via ``get``, ``get_history``, ``all_entries``) are concurrent-safe
      because ``ProvenanceEntry`` is a frozen dataclass and dict reads are atomic in CPython.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProvenanceEntry:
    """Records the origin of a single config value.

    Attributes:
        value: The value that was set.
        source: Where it came from. Format examples:
            ``"app_defaults:semantiscan"``
            ``"defaults"``
            ``"file:/home/user/.config/llmcore/config.toml"``
            ``"env:LLMCORE_PROVIDERS__OPENAI__API_KEY"``
            ``"overrides_dict"``
        key: The full dot-notation key path (e.g., ``"semantiscan.chunking.chunk_size"``).
    """

    value: Any
    source: str
    key: str

    def __repr__(self) -> str:
        return f"{self.key} = {self.value!r}  \u2190 {self.source}"


@dataclass
class ProvenanceStore:
    """Stores provenance information for all config keys.

    Tracks both the current (winning) provenance entry for each key and
    the full history of overrides, enabling inspection of the complete
    merge chain.

    Attributes:
        _entries: Current (final) provenance for each key.
        _history: Previous provenance entries for keys that were overridden.
    """

    _entries: dict[str, ProvenanceEntry] = field(default_factory=dict)
    _history: dict[str, list[ProvenanceEntry]] = field(default_factory=dict)

    def record(self, key: str, value: Any, source: str) -> None:
        """Record that a key was set to a value from a source.

        If the key already has an entry, the previous entry is moved
        to history (showing the chain of overrides).

        Args:
            key: Dot-notation key path (e.g., ``"database.host"``).
            value: The value being set.
            source: Source label (e.g., ``"file:config.toml"``).
        """
        entry = ProvenanceEntry(value=value, source=source, key=key)

        if key in self._entries:
            # Move current to history before replacing
            if key not in self._history:
                self._history[key] = []
            self._history[key].append(self._entries[key])

        self._entries[key] = entry

    def get(self, key: str) -> ProvenanceEntry | None:
        """Get the current provenance for a key.

        Args:
            key: Dot-notation key path.

        Returns:
            The current ``ProvenanceEntry``, or ``None`` if not tracked.
        """
        return self._entries.get(key)

    def get_history(self, key: str) -> list[ProvenanceEntry]:
        """Get the full override history for a key (oldest first).

        Returns all entries from the first set through to the current
        (winning) value.

        Args:
            key: Dot-notation key path.

        Returns:
            List of ``ProvenanceEntry`` from first set to current value.
            Empty list if key was never recorded.
        """
        history = list(self._history.get(key, []))
        current = self._entries.get(key)
        if current:
            history.append(current)
        return history

    def all_entries(self) -> dict[str, ProvenanceEntry]:
        """Get all current provenance entries.

        Returns:
            Shallow copy of the entries dict mapping key paths to their
            current ``ProvenanceEntry``.
        """
        return dict(self._entries)

    def sources_summary(self) -> dict[str, int]:
        """Count how many keys came from each source category.

        Groups by the prefix before the first ``:``. For example,
        ``"file:/path/to/config.toml"`` groups under ``"file"``.

        Returns:
            Dict mapping source categories to key counts.
        """
        counts: dict[str, int] = {}
        for entry in self._entries.values():
            base_source = entry.source.split(":")[0]
            counts[base_source] = counts.get(base_source, 0) + 1
        return counts
