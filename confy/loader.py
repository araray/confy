"""
confy.loader
------------

Core configuration loader:

- JSON & TOML support
- Dot-notation access (`cfg.section.key`)
- Environment-variable overrides with a prefix
- Caller-provided dict overrides
- Defaults & mandatory-key enforcement

Precedence:
    defaults → config file → environment variables → overrides_dict
"""

import os
import json
import toml
from typing import Mapping

from .exceptions import MissingMandatoryConfig

def deep_merge(a: dict, b: dict) -> dict:
    """
    Recursively merge dict b into dict a; values in b take precedence.
    """
    for k, v in b.items():
        if k in a and isinstance(a[k], dict) and isinstance(v, dict):
            a[k] = deep_merge(a[k], v)
        else:
            a[k] = v
    return a

def set_by_dot(cfg: dict, key: str, value):
    """
    Set a nested dict value given a dot-notated key.
    """
    parts = key.split('.')
    d = cfg
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = value

def get_by_dot(cfg: dict, key: str):
    """
    Retrieve a nested dict value by dot-notated key.
    Raises KeyError if any part is missing.
    """
    d = cfg
    for p in key.split('.'):
        d = d[p]
    return d

class Config:
    """
    Main confy configuration class.

    Parameters:
      - file_path: Path to JSON or TOML file.
      - prefix:   Env-var prefix (e.g. "MYAPP_CONF"). Scans for PREFIX_KEY1_KEY2.
      - overrides_dict: Mapping[str,object] of dot-keys → values.
      - defaults: dict of default settings.
      - mandatory: list[str] of dot-keys that must be present.

    Dot-notation access:
        cfg = Config(...)
        host = cfg.db.host
    """

    def __init__(self,
                 file_path: str = None,
                 prefix: str = None,
                 overrides_dict: Mapping[str, object] = None,
                 defaults: dict = None,
                 mandatory: list[str] = None):
        # 1) Start with defaults
        self._data = {}
        if defaults:
            deep_merge(self._data, defaults)

        # 2) Load from file (JSON or TOML)
        if file_path:
            ext = os.path.splitext(file_path)[1].lower()
            with open(file_path, 'r') as f:
                if ext == '.toml':
                    loaded = toml.load(f)
                elif ext == '.json':
                    loaded = json.load(f)
                else:
                    raise ValueError(f"Unsupported config file type: {ext}")
            deep_merge(self._data, loaded)

        # 3) Override via environment variables
        if prefix:
            self._apply_env(prefix)

        # 4) Override via caller-provided dict
        if overrides_dict:
            for key, val in overrides_dict.items():
                set_by_dot(self._data, key, val)

        # 5) Enforce mandatory keys
        if mandatory:
            self._validate_mandatory(mandatory)

    def _apply_env(self, prefix: str):
        """
        Scan os.environ for PREFIX_KEY1_KEY2=val,
        map KEY1_KEY2 → key1.key2, JSON-parse if possible.
        """
        plen = len(prefix) + 1
        for var, raw in os.environ.items():
            if var.startswith(prefix + "_"):
                dot_key = var[plen:].lower().replace("_", ".")
                try:
                    val = json.loads(raw)
                except Exception:
                    val = raw
                set_by_dot(self._data, dot_key, val)

    def _validate_mandatory(self, keys: list[str]):
        """Raise MissingMandatoryConfig if any dot-key is missing."""
        missing = []
        for k in keys:
            try:
                get_by_dot(self._data, k)
            except KeyError:
                missing.append(k)
        if missing:
            raise MissingMandatoryConfig(missing)

    def __getattr__(self, name: str):
        """
        Allow attribute access: cfg.section.key.
        Returns a nested Config for dict values.
        """
        try:
            val = get_by_dot(self._data, name)
        except KeyError:
            raise AttributeError(f"No such config key: {name}")
        if isinstance(val, dict):
            sub = Config()
            sub._data = val
            return sub
        return val

    def as_dict(self) -> dict:
        """Return a shallow copy of the internal config dict."""
        return self._data.copy()
