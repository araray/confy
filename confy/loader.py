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
            # Ensure d is dict-like before accessing key
            if not hasattr(d, '__getitem__'):
                 raise TypeError(f"Cannot access key '{p}' on non-dictionary item in path '{key}'")
            d = d[p] # Direct access
        return d
    except KeyError as e:
        missing_part = e.args[0] if e.args else p
        raise KeyError(f"Key path '{key}' not found (missing part: '{missing_part}')") from None
    except TypeError as e:
        # Catch errors like trying d[p] when d is not a dict
        raise TypeError(f"Invalid access path '{key}': {e}") from e

class Config(dict): # Inherit from dict
    """
    Configuration class providing dot-notation access, inheriting from dict.
    Loads configuration from defaults, file, environment variables, and overrides.
    Ensures nested dictionaries are also accessible via dot notation.
    """

    def __init__(self, *args,
                 file_path: str = None,
                 prefix: str = None,
                 overrides_dict: Mapping[str, object] = None,
                 defaults: dict = None,
                 mandatory: list[str] = None,
                 **kwargs):

        # Initialize the dictionary part first
        # Capture initial data passed positionally or via kwargs
        initial_data = args[0] if args and isinstance(args[0], dict) else {}
        initial_data.update(kwargs)
        super().__init__(initial_data)

        # --- Configuration Loading Logic ---
        # This block runs *only* if this is the top-level Config object
        # (i.e., not called recursively from _wrap_nested_dicts)
        # We can detect this by checking if file_path or defaults were passed.
        if file_path is not None or defaults is not None or prefix is not None:
            log.debug(f"DEBUG [confy.__init__]: Initializing top-level Config.")
            # 1. Start with a deep copy of defaults
            merged_data = copy.deepcopy(defaults) if defaults else {}
            # 2. Merge initial data (from args/kwargs) into defaults copy
            deep_merge(merged_data, self)

            # 3. Load from file and merge
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

            # 4. Update self with the fully merged data
            self.clear()
            self.update(merged_data)
            log.debug(f"DEBUG [confy.__init__]: Data after file/defaults merge.")

            # 5. Apply environment variable overrides
            if prefix: self._apply_env(prefix)

            # 6. Apply explicit overrides dictionary
            if overrides_dict:
                for key, val in overrides_dict.items(): set_by_dot(self, key, val)
            log.debug(f"DEBUG [confy.__init__]: Applied overrides.")

            # 7. Recursively wrap nested dictionaries *after* all merges/overrides
            self._wrap_nested_dicts()
            log.debug(f"DEBUG [confy.__init__]: Wrapped nested dicts.")

            # 8. Enforce mandatory keys on the final structure
            if mandatory: self._validate_mandatory(mandatory)
            log.debug(f"DEBUG [confy.__init__]: Top-level Config initialization complete.")
        else:
            # If called for a nested dict (no file_path/defaults/prefix passed),
            # just wrap its contents immediately.
            self._wrap_nested_dicts()
            log.debug(f"DEBUG [confy.__init__]: Initialized nested Config.")


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


    def _validate_mandatory(self, keys: list[str]):
        """Checks for mandatory keys using the fixed get_by_dot."""
        missing = []
        for k in keys:
            try: get_by_dot(self, k)
            except KeyError: missing.append(k)
        if missing: raise MissingMandatoryConfig(missing)
        log.debug(f"DEBUG [confy._validate_mandatory]: All mandatory keys present: {keys}")


    def _wrap_nested_dicts(self):
        """Recursively converts nested dicts to Config objects."""
        # Use list(self.items()) to iterate over a snapshot, allowing modification
        for key, value in list(self.items()):
            if isinstance(value, dict):
                # Ensure we don't re-wrap an already wrapped Config object
                if not isinstance(value, Config):
                    # Convert plain dict to Config object, passing the dict as initial data
                    self[key] = Config(value) # Calls __init__ for the nested dict
            elif isinstance(value, list):
                # Handle lists containing dictionaries
                new_list = []
                for i, item in enumerate(value):
                    if isinstance(item, dict) and not isinstance(item, Config):
                        new_list.append(Config(item)) # Convert dicts in lists
                    else:
                        new_list.append(item) # Keep other items as is
                # Only update if the list actually changed
                if new_list != value:
                    self[key] = new_list


    # --- Attribute Access Magic Methods ---

    def __getattr__(self, name: str) -> Any:
        """Allows accessing dictionary keys as attributes (e.g., cfg.key)."""
        # Prevent access to private/protected attributes or methods
        if name.startswith('_'):
             raise AttributeError(f"Attempted to access private attribute: {name}")
        try:
            # Standard dictionary access (__getitem__)
            value = self[name]
            log.debug(f"DEBUG [confy.__getattr__]: Accessed key '{name}'. Type: {type(value)}")
            return value
        except KeyError:
            # If key doesn't exist, raise AttributeError as expected
            log.debug(f"DEBUG [confy.__getattr__]: Key '{name}' not found. Raising AttributeError.")
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'") from None

    def __setattr__(self, name: str, value: Any):
        """Allows setting dictionary keys as attributes (e.g., cfg.key = value)."""
        # Prevent setting private/protected attributes directly
        if name.startswith('_'):
             super().__setattr__(name, value) # Allow internal assignments
             return

        # If the value being assigned is a dict, wrap it in Config
        if isinstance(value, dict) and not isinstance(value, Config):
             wrapped_value = Config(value)
        else:
             wrapped_value = value

        log.debug(f"DEBUG [confy.__setattr__]: Setting '{name}' = {wrapped_value!r}")
        # Use standard dictionary assignment (__setitem__)
        self[name] = wrapped_value

    def __delattr__(self, name: str):
        """Allows deleting dictionary keys using attribute deletion (e.g., del cfg.key)."""
        if name.startswith('_'):
             raise AttributeError(f"Cannot delete private attribute: {name}")
        try:
            log.debug(f"DEBUG [confy.__delattr__]: Deleting '{name}'")
            del self[name] # Use standard dictionary deletion (__delitem__)
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
