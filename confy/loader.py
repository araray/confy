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
    """Retrieve a nested dict value by dot-notated key."""
    d = cfg
    for p in key.split('.'):
        if not isinstance(d, dict) or p not in d:
             raise KeyError(f"Key '{p}' not found in path '{key}'")
        d = d[p]
    return d

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

        # Initialize the dictionary part first (handles args like initial data)
        super().__init__(*args, **kwargs)

        # --- Configuration Loading Logic ---
        # 1. Start with a deep copy of defaults
        merged_data = copy.deepcopy(defaults) if defaults else {}

        # 2. Merge initial data provided via args/kwargs (if any)
        #    The super().__init__ already handled this, but we merge defaults first.
        #    So, merge self (which contains initial data) into the defaults copy.
        deep_merge(merged_data, self)

        # 3. Load from file and merge
        if file_path:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Configuration file not found: {file_path}")
            ext = os.path.splitext(file_path)[1].lower()
            try:
                with open(file_path, 'rb' if ext == '.toml' else 'r') as f:
                    if ext == '.toml': loaded = tomllib.load(f)
                    elif ext == '.json': loaded = json.load(f)
                    else: raise ValueError(f"Unsupported config file type: {ext}")
                log.debug(f"DEBUG [confy.__init__]: Loaded from file {file_path}")
                deep_merge(merged_data, loaded) # Merge file content
            except Exception as e:
                raise RuntimeError(f"Error loading configuration file {file_path}: {e}") from e

        # 4. Update self with the fully merged data so far
        #    We use update() which is a standard dict method.
        self.update(merged_data)
        log.debug(f"DEBUG [confy.__init__]: Data after file/defaults merge.")

        # 5. Apply environment variable overrides directly to self
        if prefix: self._apply_env(prefix)

        # 6. Apply explicit overrides dictionary
        if overrides_dict:
            for key, val in overrides_dict.items():
                set_by_dot(self, key, val) # Use self here
        log.debug(f"DEBUG [confy.__init__]: Applied overrides.")

        # 7. Recursively wrap nested dictionaries *after* all merges/overrides
        self._wrap_nested_dicts()
        log.debug(f"DEBUG [confy.__init__]: Wrapped nested dicts.")

        # 8. Enforce mandatory keys on the final structure
        if mandatory: self._validate_mandatory(mandatory)
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
                set_by_dot(self, dot_key, val) # Use self
                applied_count += 1
        log.debug(f"DEBUG [confy._apply_env]: Applied {applied_count} env vars with prefix '{prefix}'.")

    def _validate_mandatory(self, keys: list[str]):
        """Checks for mandatory keys using dot notation."""
        missing = []
        for k in keys:
            try: get_by_dot(self, k) # Use self
            except KeyError: missing.append(k)
        if missing: raise MissingMandatoryConfig(missing)
        log.debug(f"DEBUG [confy._validate_mandatory]: All mandatory keys present: {keys}")

    def _wrap_nested_dicts(self):
        """Recursively converts nested dicts to Config objects."""
        # Iterate over a copy of items to allow modification during iteration
        for key, value in list(self.items()):
            if isinstance(value, dict) and not isinstance(value, Config):
                # Convert plain dict to Config object, passing the dict as initial data
                self[key] = Config(value)
                # No need to call _wrap_nested_dicts here, it's handled by the new object's __init__
            elif isinstance(value, list):
                # Handle lists containing dictionaries
                new_list = []
                for item in value:
                    if isinstance(item, dict) and not isinstance(item, Config):
                        new_list.append(Config(item)) # Convert dicts in lists
                    else:
                        new_list.append(item) # Keep other items as is
                self[key] = new_list


    # --- Attribute Access Magic Methods ---

    def __getattr__(self, name: str) -> Any:
        """Allows accessing dictionary keys as attributes (e.g., cfg.key)."""
        # Check if the key exists using standard dict access (__getitem__)
        # This will raise KeyError if the key is missing.
        try:
            value = self[name]
            log.debug(f"DEBUG [confy.__getattr__]: Accessed key '{name}' successfully.")
            return value
        except KeyError:
            # Convert KeyError to AttributeError for getattr behavior
            log.debug(f"DEBUG [confy.__getattr__]: Key '{name}' not found. Raising AttributeError.")
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'") from None

    def __setattr__(self, name: str, value: Any):
        """Allows setting dictionary keys as attributes (e.g., cfg.key = value)."""
        # Use standard dict item assignment (__setitem__)
        log.debug(f"DEBUG [confy.__setattr__]: Setting '{name}' = {value!r}")
        self[name] = value

    def __delattr__(self, name: str):
        """Allows deleting dictionary keys using attribute deletion (e.g., del cfg.key)."""
        # Use standard dict item deletion (__delitem__)
        try:
            log.debug(f"DEBUG [confy.__delattr__]: Deleting '{name}'")
            del self[name]
        except KeyError:
            # Convert KeyError to AttributeError for delattr behavior
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'") from None

    # --- Utility Methods ---

    def get(self, key: str, default: Any = None) -> Any:
        """Provides dictionary-like .get() access using dot-notation."""
        try:
            return get_by_dot(self, key) # Use self
        except KeyError:
            return default

    def as_dict(self) -> dict:
        """
        Returns a standard dictionary representation, recursively converting
        nested Config objects back to plain dicts.
        """
        plain_dict = {}
        for key, value in self.items():
            if isinstance(value, Config):
                plain_dict[key] = value.as_dict() # Recurse
            elif isinstance(value, list):
                plain_dict[key] = [
                    item.as_dict() if isinstance(item, Config) else item
                    for item in value
                ] # Handle lists
            else:
                plain_dict[key] = value
        return plain_dict

    def __repr__(self) -> str:
        """String representation."""
        # Use the standard dict repr for clarity
        return f"{type(self).__name__}({super().__repr__()})"

    def __contains__(self, key: str) -> bool:
        """Allows checking key existence with 'in' using dot-notation."""
        try:
            get_by_dot(self, key) # Use self
            return True
        except KeyError:
            return False
