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

def set_by_dot(cfg: dict, key: str, value: Any):
    """
    Set a nested dict value given a dot-notated key.
    Creates intermediate dictionaries if they don't exist.
    """
    parts = key.split('.')
    d = cfg
    for p in parts[:-1]:
        # Ensure intermediate keys are dictionaries
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
        # Check if key exists at current level
        if not isinstance(d, dict) or p not in d:
             raise KeyError(f"Key '{p}' not found in path '{key}'")
        d = d[p]
    return d

class Config:
    """
    Main confy configuration class.

    Allows accessing configuration values using dot notation (e.g., `cfg.section.key`).
    Loads configuration from defaults, a file (JSON/TOML), environment variables,
    and an optional overrides dictionary.

    Parameters:
      file_path (str, optional): Path to JSON or TOML file. Defaults to None.
      prefix (str, optional): Environment variable prefix (e.g., "MYAPP_CONF").
                              Scans for PREFIX_KEY1_KEY2. Defaults to None.
      overrides_dict (Mapping[str, object], optional): Dictionary of dot-keys to values
                                                       to apply last. Defaults to None.
      defaults (dict, optional): Dictionary of default settings. Defaults to None.
      mandatory (list[str], optional): List of dot-keys that must be present
                                       after all merges. Defaults to None.

    Raises:
        MissingMandatoryConfig: If any key in `mandatory` is missing.
        ValueError: If `file_path` has an unsupported extension.
        FileNotFoundError: If `file_path` does not exist.
        Exception: For errors during file parsing or environment variable processing.
    """

    def __init__(self,
                 file_path: str = None,
                 prefix: str = None,
                 overrides_dict: Mapping[str, object] = None,
                 defaults: dict = None,
                 mandatory: list[str] = None):

        # Use a temporary dict for merging to avoid modifying the input `defaults`
        merged_data = {}
        if defaults:
            # Ensure we work with a copy if defaults are provided
            merged_data = defaults.copy() # Shallow copy is usually sufficient here

        # 2) Load from file (JSON or TOML)
        if file_path:
            if not os.path.exists(file_path):
                 raise FileNotFoundError(f"Configuration file not found: {file_path}")
            ext = os.path.splitext(file_path)[1].lower()
            try:
                with open(file_path, 'rb' if ext == '.toml' else 'r') as f: # TOML needs 'rb'
                    if ext == '.toml':
                        loaded = tomllib.load(f)
                    elif ext == '.json':
                        loaded = json.load(f)
                    else:
                        raise ValueError(f"Unsupported config file type: {ext}")
                # Deep merge file content into existing data
                deep_merge(merged_data, loaded)
            except Exception as e:
                 raise RuntimeError(f"Error loading configuration file {file_path}: {e}") from e

        # Store the merged data internally
        # We use a leading underscore to indicate it's intended for internal use,
        # though Python doesn't enforce privacy.
        self._data = merged_data

        # 3) Override via environment variables
        if prefix:
            self._apply_env(prefix) # Modifies self._data in place

        # 4) Override via caller-provided dict
        if overrides_dict:
            for key, val in overrides_dict.items():
                set_by_dot(self._data, key, val) # Modifies self._data in place

        # 5) Enforce mandatory keys
        if mandatory:
            self._validate_mandatory(mandatory)

    def _apply_env(self, prefix: str):
        """
        Scan os.environ for PREFIX_KEY1_KEY2=val,
        map KEY1_KEY2 → key1.key2, JSON-parse if possible.
        Modifies self._data directly.
        """
        # Ensure prefix ends with an underscore if not already present
        prefix = prefix.rstrip('_') + '_'
        plen = len(prefix)

        for var, raw in os.environ.items():
            if var.startswith(prefix):
                # Convert KEY1_KEY2 to key1.key2
                dot_key = var[plen:].lower().replace("_", ".")
                if not dot_key: continue # Skip if only prefix matches

                try:
                    # Attempt to parse value as JSON (handles bools, numbers, lists, dicts)
                    val = json.loads(raw)
                except json.JSONDecodeError:
                    # Fallback to raw string if not valid JSON
                    val = raw
                except Exception as e:
                     # Log potential unexpected errors during JSON parsing
                     print(f"Warning: Could not JSON parse env var {var}: {e}. Using raw string value.")
                     val = raw

                # Set the value in the internal data dictionary
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

    def __getattr__(self, name: str) -> Any:
        """
        Allow attribute access: cfg.section.key.
        Looks up `name` in the current level's data.
        Returns a nested Config object for dictionary values.

        Args:
            name (str): The attribute name being accessed.

        Returns:
            Any: The value associated with the attribute name. If the value is a
                 dictionary, returns a new Config instance wrapping that dictionary.

        Raises:
            AttributeError: If the attribute `name` is not found in the configuration data.
        """
        if name.startswith('_'):
             # Prevent access to internal attributes like _data via getattr
             raise AttributeError(f"Attempted to access internal attribute: {name}")

        try:
            # Look for the key `name` directly in the current object's data
            value = self._data[name]
        except KeyError:
            # Raise AttributeError if the key doesn't exist at this level
            raise AttributeError(f"No such config key: {name}") from None

        # If the retrieved value is a dictionary, wrap it in a new Config object
        # to allow further nested attribute access (e.g., cfg.auth.two_fa)
        if isinstance(value, dict):
            # Create a new Config instance *without* running the full init logic again
            nested_config = Config()
            # Directly assign the nested dictionary to the new instance's internal data
            nested_config._data = value
            return nested_config
        else:
            # If it's not a dictionary, return the value directly
            return value

    def get(self, key: str, default: Any = None) -> Any:
        """
        Provides dictionary-like .get() access with a default value.
        Uses dot-notation for the key.

        Args:
            key (str): The dot-notated key to retrieve (e.g., "server.port").
            default (Any, optional): The value to return if the key is not found.
                                     Defaults to None.

        Returns:
            Any: The value found for the key, or the default value.
        """
        try:
            return get_by_dot(self._data, key)
        except KeyError:
            return default

    def as_dict(self) -> dict:
        """
        Return a shallow copy of the internal config dictionary.
        Modifying the returned dictionary will not affect the Config object.
        """
        return self._data.copy()

    def __repr__(self) -> str:
        """Provide a string representation of the Config object."""
        # Show the internal data for clarity
        return f"Config({self._data})"

    def __contains__(self, key: str) -> bool:
        """
        Allows checking for key existence using the 'in' operator (e.g., 'server.port' in cfg).
        Uses dot-notation.
        """
        try:
            get_by_dot(self._data, key)
            return True
        except KeyError:
            return False
