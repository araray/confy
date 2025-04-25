"""
confy.loader
------------

Core configuration loader using dictionary inheritance for robust attribute access.
"""

import os
import json
# Use tomllib for Python >= 3.11
import tomllib
from typing import Mapping, Any
import logging
import copy # For deepcopy

from .exceptions import MissingMandatoryConfig

log = logging.getLogger(__name__) # Logger for confy loader

def deep_merge(a: dict, b: dict) -> dict:
    """Recursively merge dict b into dict a; values in b take precedence."""
    for k, v in b.items():
        if k in a and isinstance(a[k], dict) and isinstance(v, dict):
            a[k] = deep_merge(a[k], v)
        else:
            a[k] = v
    return a

def set_by_dot(cfg: dict, key: str, value: Any):
    """Set a nested dict value given a dot-notated key."""
    parts = key.split('.')
    d = cfg
    for p in parts[:-1]:
        if p not in d or not isinstance(d[p], dict):
            d[p] = {}
        d = d[p]
    d[parts[-1]] = value

def get_by_dot(cfg: dict, key: str) -> Any:
    """Retrieve a nested dict value by dot-notated key using direct access."""
    d = cfg
    try:
        for p in key.split('.'):
            d = d[p] # Direct access
        return d
    except KeyError as e:
        missing_part = e.args[0] if e.args else p
        raise KeyError(f"Key path '{key}' not found (missing part: '{missing_part}')") from None
    except TypeError as e:
        raise TypeError(f"Invalid access path '{key}': encountered non-dictionary item.") from e

class Config(dict): # Inherit from dict
    """
    Configuration class providing dot-notation access, inheriting from dict.
    Loads configuration from defaults, file, environment variables, and overrides.
    """

    def __init__(self, *args,
                 file_path: str = None,
                 prefix: str = None,
                 overrides_dict: Mapping[str, object] = None,
                 defaults: dict = None,
                 mandatory: list[str] = None,
                 _is_nested_call: bool = False, # Internal flag
                 **kwargs):

        # Initialize dict part first
        # If it's a nested call, args[0] will be the sub-dictionary
        initial_data = args[0] if args and isinstance(args[0], dict) else {}
        initial_data.update(kwargs)
        super().__init__(initial_data)

        # --- Full Loading Logic (Only for top-level calls) ---
        if not _is_nested_call:
            log.debug(f"DEBUG [confy.__init__]: Initializing top-level Config.")
            merged_data = copy.deepcopy(defaults) if defaults else {}
            deep_merge(merged_data, self) # Merge initial data into defaults copy

            if file_path:
                # File loading logic... (same as before)
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

            self.clear() # Clear initial data from super init
            self.update(merged_data) # Update self with fully merged data
            log.debug(f"DEBUG [confy.__init__]: Data after file/defaults merge.")

            if prefix: self._apply_env(prefix)
            if overrides_dict:
                for key, val in overrides_dict.items(): set_by_dot(self, key, val)
            log.debug(f"DEBUG [confy.__init__]: Applied overrides.")

            # Wrap nested dicts *after* all data is loaded and merged
            self._wrap_nested_dicts()
            log.debug(f"DEBUG [confy.__init__]: Wrapped nested dicts.")

            if mandatory: self._validate_mandatory(mandatory)
            log.debug(f"DEBUG [confy.__init__]: Top-level Config initialization complete.")
        else:
             # If it's a nested call, just wrap its own dicts
             self._wrap_nested_dicts()
             log.debug(f"DEBUG [confy.__init__]: Initialized nested Config.")


    def _apply_env(self, prefix: str):
        """Applies environment variable overrides directly to self."""
        # ... (same as before) ...
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
                set_by_dot(self, dot_key, val)
                applied_count += 1
        log.debug(f"DEBUG [confy._apply_env]: Applied {applied_count} env vars with prefix '{prefix}'.")


    def _validate_mandatory(self, keys: list[str]):
        """Checks for mandatory keys using the fixed get_by_dot."""
        # ... (same as before) ...
        missing = []
        for k in keys:
            try: get_by_dot(self, k)
            except KeyError: missing.append(k)
        if missing: raise MissingMandatoryConfig(missing)
        log.debug(f"DEBUG [confy._validate_mandatory]: All mandatory keys present: {keys}")


    def _wrap_nested_dicts(self):
        """Recursively converts nested dicts to Config objects."""
        # Iterate over a copy of items to allow modification
        for key, value in list(self.items()):
            if isinstance(value, dict) and not isinstance(value, Config):
                # Pass the dictionary and the internal flag
                self[key] = Config(value, _is_nested_call=True)
            elif isinstance(value, list):
                # Handle lists containing dictionaries
                self[key] = [
                    Config(item, _is_nested_call=True) if isinstance(item, dict) and not isinstance(item, Config) else item
                    for item in value
                ]


    # --- Attribute Access Magic Methods ---
    def __getattr__(self, name: str) -> Any:
        """Allows accessing dictionary keys as attributes (e.g., cfg.key)."""
        try:
            # Standard dictionary access first
            value = self[name]
            log.debug(f"DEBUG [confy.__getattr__]: Accessed key '{name}'.")
            # No need to wrap here, _wrap_nested_dicts handles it during init
            return value
        except KeyError:
            log.debug(f"DEBUG [confy.__getattr__]: Key '{name}' not found. Raising AttributeError.")
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'") from None

    def __setattr__(self, name: str, value: Any):
        """Allows setting dictionary keys as attributes (e.g., cfg.key = value)."""
        # If the value being set is a dict, wrap it
        if isinstance(value, dict) and not isinstance(value, Config):
             wrapped_value = Config(value, _is_nested_call=True)
        else:
             wrapped_value = value
        log.debug(f"DEBUG [confy.__setattr__]: Setting '{name}' = {wrapped_value!r}")
        self[name] = wrapped_value # Use standard dict access

    def __delattr__(self, name: str):
        """Allows deleting dictionary keys using attribute deletion (e.g., del cfg.key)."""
        try:
            log.debug(f"DEBUG [confy.__delattr__]: Deleting '{name}'")
            del self[name] # Use standard dict access
        except KeyError:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'") from None

    # --- Utility Methods ---
    def get(self, key: str, default: Any = None) -> Any:
        """Provides dictionary-like .get() access using dot-notation."""
        try: return get_by_dot(self, key)
        except KeyError: return default

    def as_dict(self) -> dict:
        """Returns standard dict representation, recursively converting nested Configs."""
        plain_dict = {}
        for key, value in self.items():
            if isinstance(value, Config): plain_dict[key] = value.as_dict()
            elif isinstance(value, list):
                plain_dict[key] = [item.as_dict() if isinstance(item, Config) else item for item in value]
            else: plain_dict[key] = value
        return plain_dict

    def __repr__(self) -> str:
        """String representation."""
        return f"{type(self).__name__}({super().__repr__()})"

    def __contains__(self, key: Any) -> bool:
        """Checks key existence using dot-notation for strings."""
        if not isinstance(key, str): return super().__contains__(key)
        try: get_by_dot(self, key); return True
        except KeyError: return False
