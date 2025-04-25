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

# --- REVISED get_by_dot ---
def get_by_dot(cfg: dict, key: str) -> Any:
    """
    Retrieve a nested dict value by dot-notated key using direct access.
    Raises KeyError if any part is missing or path is invalid.
    """
    d = cfg
    try:
        for p in key.split('.'):
            # Use direct dictionary access (__getitem__)
            # This avoids calling __contains__ recursively.
            d = d[p]
        return d
    except KeyError as e:
        # Re-raise KeyError with a more informative message including the full path
        # e.args[0] usually contains the missing key part
        missing_part = e.args[0] if e.args else p # p is the last attempted part
        raise KeyError(f"Key path '{key}' not found (missing part: '{missing_part}')") from None
    except TypeError as e:
        # Catch error if trying to access item on non-dict
        raise TypeError(f"Invalid access path '{key}': encountered non-dictionary item.") from e
# --- END REVISED get_by_dot ---

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
                 **kwargs):

        super().__init__(*args, **kwargs) # Initialize dict part

        merged_data = copy.deepcopy(defaults) if defaults else {}
        deep_merge(merged_data, self) # Merge initial data into defaults copy

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

        self.update(merged_data) # Update self with merged data
        log.debug(f"DEBUG [confy.__init__]: Data after file/defaults merge.")

        if prefix: self._apply_env(prefix)
        if overrides_dict:
            for key, val in overrides_dict.items(): set_by_dot(self, key, val)
        log.debug(f"DEBUG [confy.__init__]: Applied overrides.")

        self._wrap_nested_dicts() # Convert nested dicts to Config
        log.debug(f"DEBUG [confy.__init__]: Wrapped nested dicts.")

        if mandatory: self._validate_mandatory(mandatory) # Validate after everything is loaded/wrapped
        log.debug(f"DEBUG [confy.__init__]: Config initialization complete.")

    def _apply_env(self, prefix: str):
        """Applies environment variable overrides directly to self."""
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

    # --- REVISED _validate_mandatory ---
    def _validate_mandatory(self, keys: list[str]):
        """Checks for mandatory keys using the fixed get_by_dot."""
        missing = []
        for k in keys:
            try:
                get_by_dot(self, k) # Use the fixed get_by_dot
            except KeyError:
                missing.append(k) # Key not found
        if missing:
            raise MissingMandatoryConfig(missing)
        log.debug(f"DEBUG [confy._validate_mandatory]: All mandatory keys present: {keys}")
    # --- END REVISED _validate_mandatory ---

    def _wrap_nested_dicts(self):
        """Recursively converts nested dicts to Config objects."""
        for key, value in list(self.items()):
            if isinstance(value, dict) and not isinstance(value, Config):
                self[key] = Config(value) # Pass dict to constructor
            elif isinstance(value, list):
                new_list = []
                for item in value:
                    if isinstance(item, dict) and not isinstance(item, Config):
                        new_list.append(Config(item))
                    else:
                        new_list.append(item)
                self[key] = new_list

    # --- Attribute Access Magic Methods ---
    def __getattr__(self, name: str) -> Any:
        """Allows accessing dictionary keys as attributes (e.g., cfg.key)."""
        try:
            value = self[name] # Use standard dict access
            log.debug(f"DEBUG [confy.__getattr__]: Accessed key '{name}'.")
            return value
        except KeyError:
            log.debug(f"DEBUG [confy.__getattr__]: Key '{name}' not found. Raising AttributeError.")
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'") from None

    def __setattr__(self, name: str, value: Any):
        """Allows setting dictionary keys as attributes (e.g., cfg.key = value)."""
        log.debug(f"DEBUG [confy.__setattr__]: Setting '{name}' = {value!r}")
        self[name] = value # Use standard dict access

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

    # --- REVISED __contains__ ---
    def __contains__(self, key: Any) -> bool:
        """
        Checks key existence. Handles both top-level and dot-notation keys.
        Avoids recursion by calling the fixed get_by_dot.
        """
        if not isinstance(key, str): # Handle non-string keys if necessary
             return super().__contains__(key)
        try:
            get_by_dot(self, key) # Check existence using the fixed method
            return True
        except KeyError:
            return False
    # --- END REVISED __contains__ ---
