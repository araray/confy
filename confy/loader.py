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
# Use tomllib for Python >= 3.11
import tomllib
from typing import Mapping, Any
import logging

from .exceptions import MissingMandatoryConfig

log = logging.getLogger(__name__) # Logger for confy loader

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

def set_by_dot(cfg: dict, key: str, value: Any):
    """
    Set a nested dict value given a dot-notated key.
    Creates intermediate dictionaries if they don't exist.
    """
    parts = key.split('.')
    d = cfg
    for p in parts[:-1]:
        if p not in d or not isinstance(d[p], dict):
            d[p] = {}
        d = d[p]
    d[parts[-1]] = value

def get_by_dot(cfg: dict, key: str) -> Any:
    """
    Retrieve a nested dict value by dot-notated key.
    Raises KeyError if any part is missing.
    """
    d = cfg
    for p in key.split('.'):
        if not isinstance(d, dict) or p not in d:
             raise KeyError(f"Key '{p}' not found in path '{key}'")
        d = d[p]
    return d

class Config:
    """
    Main confy configuration class.
    Allows accessing configuration values using dot notation (e.g., `cfg.section.key`).
    """
    # Keeping slots and _is_nested from previous attempt
    __slots__ = ('_data', '_is_nested')

    def __init__(self,
                 file_path: str = None,
                 prefix: str = None,
                 overrides_dict: Mapping[str, object] = None,
                 defaults: dict = None,
                 mandatory: list[str] = None,
                 _nested_data: dict = None): # Internal arg for nested creation

        self._is_nested = _nested_data is not None

        if self._is_nested:
            self._data = _nested_data if isinstance(_nested_data, dict) else {}
            log.debug(f"DEBUG [confy.__init__]: Created nested Config with data keys: {list(self._data.keys())}")
        else:
            log.debug(f"DEBUG [confy.__init__]: Initializing top-level Config.")
            merged_data = {}
            if defaults: merged_data = defaults.copy()

            if file_path:
                if not os.path.exists(file_path): raise FileNotFoundError(f"Config file not found: {file_path}")
                ext = os.path.splitext(file_path)[1].lower()
                try:
                    with open(file_path, 'rb' if ext == '.toml' else 'r') as f:
                        if ext == '.toml': loaded = tomllib.load(f)
                        elif ext == '.json': loaded = json.load(f)
                        else: raise ValueError(f"Unsupported config file type: {ext}")
                    log.debug(f"DEBUG [confy.__init__]: Loaded from file {file_path}")
                    deep_merge(merged_data, loaded)
                except Exception as e: raise RuntimeError(f"Error loading config file {file_path}: {e}") from e

            self._data = merged_data
            log.debug(f"DEBUG [confy.__init__]: Data after file merge keys: {list(self._data.keys())}")

            if prefix: self._apply_env(prefix)
            if overrides_dict:
                for key, val in overrides_dict.items(): set_by_dot(self._data, key, val)
            log.debug(f"DEBUG [confy.__init__]: Data after overrides keys: {list(self._data.keys())}")

            if mandatory: self._validate_mandatory(mandatory)
            log.debug(f"DEBUG [confy.__init__]: Top-level Config initialization complete.")


    def _apply_env(self, prefix: str):
        """Applies environment variable overrides."""
        applied_count = 0
        prefix = prefix.rstrip('_') + '_'
        plen = len(prefix)
        for var, raw in os.environ.items():
            if var.startswith(prefix):
                dot_key = var[plen:].lower().replace("_", ".")
                if not dot_key: continue
                try: val = json.loads(raw)
                except json.JSONDecodeError: val = raw
                except Exception as e: log.warning(f"Warning: Could not JSON parse env var {var}: {e}. Using raw string."); val = raw
                set_by_dot(self._data, dot_key, val)
                applied_count += 1
        log.debug(f"DEBUG [confy._apply_env]: Applied {applied_count} env vars with prefix '{prefix}'.")


    def _validate_mandatory(self, keys: list[str]):
        """Checks for mandatory keys."""
        missing = [k for k in keys if k not in self]
        if missing: raise MissingMandatoryConfig(missing)
        log.debug(f"DEBUG [confy._validate_mandatory]: All mandatory keys present: {keys}")

    def __getattr__(self, name: str) -> Any:
        """Handles attribute access (e.g., cfg.section.key)."""
        is_nested_val = getattr(self, '_is_nested', 'Unknown')
        data_keys = list(self._data.keys()) if isinstance(self._data, dict) else 'Not a dict'
        log.debug(f"DEBUG [confy.__getattr__]: ENTER - Accessing '{name}' on Config(is_nested={is_nested_val})")
        log.debug(f"DEBUG [confy.__getattr__]: self._data keys: {data_keys}")

        if name.startswith('_'):
             log.error(f"DEBUG [confy.__getattr__]: Attempting access to internal attribute '{name}'. Raising AttributeError.")
             raise AttributeError(f"Attempted to access internal attribute: {name}")

        try:
            # *** Use try/except instead of 'in' check ***
            value = self._data[name]
            log.debug(f"DEBUG [confy.__getattr__]: Successfully accessed key '{name}' via self._data[name].")
        except KeyError:
            # This block should now correctly handle the case where the key is missing
            log.error(f"DEBUG [confy.__getattr__]: KeyError accessing '{name}' in _data keys: {data_keys}. Raising AttributeError.")
            raise AttributeError(f"No such config key: {name}") from None
        except TypeError as e:
             # Catch if self._data is not a dictionary somehow
             log.error(f"DEBUG [confy.__getattr__]: TypeError accessing '{name}'. self._data is not a dict? Type: {type(self._data)}. Error: {e}", exc_info=True)
             raise AttributeError(f"Configuration data is not accessible like a dictionary for key: {name}") from e


        value_type = type(value).__name__
        log.debug(f"DEBUG [confy.__getattr__]: Found key '{name}'. Value type: {value_type}")

        if isinstance(value, dict):
            log.debug(f"DEBUG [confy.__getattr__]: Value for '{name}' is dict. Creating nested Config via constructor with _nested_data.")
            nested_config = Config(_nested_data=value)
            log.debug(f"DEBUG [confy.__getattr__]: Returning nested Config for '{name}' with _data keys: {list(nested_config._data.keys())}")
            return nested_config
        else:
            log.debug(f"DEBUG [confy.__getattr__]: Returning direct value for '{name}' (type: {value_type}).")
            return value

    def get(self, key: str, default: Any = None) -> Any:
        """Dictionary-like .get() using dot-notation."""
        try: return get_by_dot(self._data, key)
        except KeyError: return default

    def as_dict(self) -> dict:
        """Returns a shallow copy of the internal data."""
        return self._data.copy()

    def __repr__(self) -> str:
        """String representation."""
        data_repr = str(self._data)
        if len(data_repr) > 100: data_repr = data_repr[:100] + '...'
        return f"Config(is_nested={getattr(self, '_is_nested', 'N/A')}, data={data_repr})"

    def __contains__(self, key: str) -> bool:
        """Allows checking key existence with 'in' using dot-notation."""
        try: get_by_dot(self._data, key); return True
        except KeyError: return False
