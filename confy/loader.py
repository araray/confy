# confy/loader.py
"""
confy.loader
------------

Core configuration loader using dictionary inheritance for robust attribute access.
Supports loading from defaults, JSON/TOML files, .env files, environment
variables, and override dictionaries.
Requires Python 3.10+.
"""

import os
import json
import copy # For deepcopy
import logging
from typing import Mapping, Any, Union, Dict, List, Optional

# Use tomli for reading TOML (works for Python 3.10+)
try:
    import tomli
except ImportError:
    try: import tomllib as tomli # Python 3.11+
    except ImportError: tomli = None

# Import load_dotenv from python-dotenv
try: from dotenv import load_dotenv, find_dotenv # Added find_dotenv for check
except ImportError: load_dotenv, find_dotenv = None, None

from .exceptions import MissingMandatoryConfig

log = logging.getLogger(__name__) # Logger for confy loader

# --- Helper Functions ---

def deep_merge(base: dict, updates: dict) -> dict:
    """
    Recursively merge the `updates` dictionary into the `base` dictionary.

    - Creates a deep copy of `base` to avoid modifying the original.
    - Iterates through `updates`:
        - If a key exists in `base` and BOTH corresponding values are DICTIONARIES
          (including dict subclasses like Config), it merges them recursively.
        - Otherwise (key not in `base`, or either value is not a dictionary -
          e.g., list, bool, int, str), the value from `updates` completely
          overwrites the value in `base`.

    Args:
        base: The base dictionary (or Config object).
        updates: The dictionary with updates to merge into `base`.

    Returns:
        A new dictionary representing the merged result.
    """
    # Start with a deep copy of 'base'.
    merged = copy.deepcopy(base)

    for key, value_updates in updates.items():
        value_base = merged.get(key)

        # Check if both values are dictionary-like (standard dict or Config)
        # Use isinstance to handle dict subclasses correctly.
        is_dict_like_base = isinstance(value_base, dict)
        is_dict_like_updates = isinstance(value_updates, dict)

        if is_dict_like_base and is_dict_like_updates:
            # Both are dictionary-like, merge recursively
            merged[key] = deep_merge(value_base, value_updates)
        else:
            # If either value is not a dictionary (e.g., list, bool, int, str),
            # or the key is new in 'updates', the value from `updates` overwrites.
            # Ensure Config objects from updates are preserved, not just deepcopied
            if isinstance(value_updates, Config):
                 merged[key] = value_updates # Assign Config object directly
            else:
                 merged[key] = copy.deepcopy(value_updates)
            # log.debug(f"deep_merge: Overwriting key '{key}' with value type {type(value_updates).__name__}")

    return merged


def set_by_dot(cfg: Union[dict, 'Config'], key: str, value: Any, create_missing: bool = True):
    """
    Set a nested dictionary value using a dot-notated key string.

    Works on both standard dicts and Config objects.
    Creates intermediate dictionaries along the path if they do not exist,
    unless create_missing is False. If a part of the path exists but is not a
    dictionary, it will be overwritten with a new dictionary (a warning will
    be logged) only if create_missing is True.

    Args:
        cfg: The dictionary or Config object to modify.
        key: The dot-notation string representing the path (e.g., "database.host").
        value: The value to set at the specified path.
        create_missing: If True, create intermediate dicts. If False, raise
                        KeyError or TypeError if the path is invalid.

    Raises:
        KeyError: If a key part is not found and create_missing is False.
        TypeError: If a path segment is not a dict and create_missing is False.
    """
    parts = key.split('.')
    d = cfg # Start traversal from the root dictionary/Config
    # Traverse the path up to the second-to-last part
    for i, p in enumerate(parts[:-1]):
        current_val = d.get(p) # Use .get() for safe access on both dict/Config

        if not isinstance(current_val, (dict, Config)): # Check if it's dict-like
            if not create_missing:
                if p not in d:
                    raise KeyError(f"Path segment '{p}' not found in key '{key}'")
                else:
                    raise TypeError(f"Path segment '{p}' (type: {type(current_val).__name__}) in key '{key}' is not a dictionary.")
            # If create_missing is True:
            if p in d:
                 log.warning(f"Warning: Overwriting non-dictionary key '{p}' (type: {type(current_val).__name__}) in path '{key}' during set_by_dot.")
            # Create a new dictionary (or Config if target is Config)
            new_dict = Config({}) if isinstance(cfg, Config) else {}
            d[p] = new_dict
        # Move deeper into the dictionary structure
        d = d[p]

    # Set the value at the final key part
    final_key = parts[-1]
    if not create_missing and final_key not in d:
        # If the final key itself is missing and we are not creating.
        raise KeyError(f"Final key '{final_key}' not found in path '{key}'")

    # Wrap value if setting within a Config object and value is a dict
    if isinstance(d, Config) and isinstance(value, dict) and not isinstance(value, Config):
         d[final_key] = Config(value)
    else:
         d[final_key] = value


def get_by_dot(cfg: Union[Mapping, 'Config'], key: str) -> Any:
    """
    Retrieve a nested value from a Mapping (like dict or Config) using a dot-notated key.

    Args:
        cfg: The dictionary or Config object to retrieve from.
        key: The dot-notation string representing the path (e.g., "database.host").

    Returns:
        The value found at the specified path.

    Raises:
        KeyError: If any part of the key path does not exist.
        TypeError: If an attempt is made to access a key on a non-dictionary item
                   during path traversal (e.g., accessing "a.b" when "a" is an integer).
    """
    d = cfg # Start traversal from the root
    parts = key.split('.')
    current_path_parts = [] # Keep track of the path traversed so far for error messages
    try:
        for i, p in enumerate(parts):
            current_path_parts.append(p)
            # Ensure the current level 'd' is a dictionary-like object before indexing
            # Check Mapping for dicts, Config for Config objects
            if not isinstance(d, (Mapping, Config)):
                 current_path = '.'.join(current_path_parts[:-1]) # Path up to the error point
                 raise TypeError(f"Cannot access key '{p}' on non-dictionary item at path '{current_path}' (item type: {type(d).__name__})")

            # Access the next level using standard item access (works for both dict and Config).
            # This will raise KeyError if 'p' is not in 'd'.
            d = d[p]

        # Return the final value after successful traversal
        return d
    except KeyError as e:
        # If a key is not found during traversal
        missing_part = e.args[0] if e.args else p # Get the missing key from the exception or last part
        found_path = '.'.join(current_path_parts[:-1]) # The valid path leading up to the missing part
        raise KeyError(f"Key path '{key}' not found (missing part: '{missing_part}' at path '{found_path}')") from None
    except TypeError as e:
        # Catch other TypeErrors that might occur during access
        raise TypeError(f"Invalid access path '{key}': {e}") from e

def _parse_value(raw_value: Any) -> Any:
    """
    Attempts to parse a string value into Python types (bool, int, float, JSON list/dict).

    Handles common string representations like 'true', 'false', 'null', numbers.
    Attempts JSON decoding for strings starting with '{', '[', or '"'.
    Falls back to the original string if no specific parsing rule applies.

    Args:
        raw_value: The value to parse. If not a string, it's returned directly.

    Returns:
        The parsed value (bool, int, float, list, dict, None) or the original value.
    """
    # If the input is not a string, return it as is.
    if not isinstance(raw_value, str):
        return raw_value

    stripped_val = raw_value.strip()
    # log.debug(f"DEBUG [_parse_value]: Attempting to parse '{stripped_val}' (original: '{raw_value}')")

    # Explicit checks for boolean and null strings (case-insensitive)
    lower_val = stripped_val.lower()
    if lower_val == 'true':
        # log.debug("DEBUG [_parse_value]: Parsed as True (boolean)")
        return True
    if lower_val == 'false':
        # log.debug("DEBUG [_parse_value]: Parsed as False (boolean)")
        return False
    if lower_val == 'null':
        # log.debug("DEBUG [_parse_value]: Parsed as None")
        return None

    # Attempt to parse as integer
    try:
        result = int(stripped_val)
        # log.debug(f"DEBUG [_parse_value]: Parsed as {result} (integer)")
        return result
    except ValueError:
        # If not int, attempt to parse as float
        try:
            result = float(stripped_val)
            # log.debug(f"DEBUG [_parse_value]: Parsed as {result} (float)")
            return result
        except ValueError:
            # If not a simple number, proceed to JSON check
            pass

    # Attempt to parse as JSON, but only if it looks like JSON
    # (starts with '{', '[', or '"' for quoted strings)
    try:
        # Check if it looks like JSON before attempting to parse
        if stripped_val.startswith(("{", "[", '"')) and len(stripped_val) > 1:
             # Check if it ends appropriately for potential JSON structures
             if (stripped_val.startswith("{") and stripped_val.endswith("}")) or \
                (stripped_val.startswith("[") and stripped_val.endswith("]")) or \
                (stripped_val.startswith('"') and stripped_val.endswith('"')):
                 result = json.loads(stripped_val)
                 # log.debug(f"DEBUG [_parse_value]: Parsed as JSON: {result}")
                 return result
    except json.JSONDecodeError:
        # If JSON parsing fails, it's likely just a plain string
        # log.debug("DEBUG [_parse_value]: Failed to parse as JSON.")
        pass

    # Fallback: return the original string value if no other parsing matched.
    # log.debug(f"DEBUG [_parse_value]: Falling back to original string: '{raw_value}'")
    return raw_value

# --- Config Class ---

class Config(dict):
    """
    Configuration class providing dictionary-like access with dot-notation.

    Inherits from `dict`, allowing standard dictionary operations. Adds functionality
    for loading configuration from multiple sources with defined precedence and
    accessing nested values using attribute-style dot notation (e.g., `cfg.database.host`).

    Loading Precedence (lowest to highest priority):
    1.  **Defaults dictionary (`defaults`)**: Base values provided programmatically.
    2.  **Initial data (`*args`, `**kwargs`)**: Values passed directly during `Config` instantiation.
    3.  **Config file (`file_path`)**: Values loaded from a specified JSON or TOML file.
        *Special TOML Handling*: Keys within TOML sections (e.g., `list_items` under `[new_section]`)
        may be "promoted" to the root level if they match a root-level key in `defaults`.
    4.  **Environment variables (`prefix`)**: Values loaded from `os.environ`. This includes
        variables potentially loaded from a `.env` file in Step 0. Environment variables
        matching the specified `prefix` are processed using simple `_` to `.` conversion
        (e.g., `MYAPP_DB_HOST` -> `db.host`). Values are parsed using `_parse_value`.
        *Remapping*: After initialization and wrapping, a check is performed to see if dot-separated keys
        from env vars (e.g., `feature.flags.new.ui`) correspond to existing underscore-separated keys
        (e.g., `feature_flags.new_ui`). If so, the value is moved to the underscore key, and the
        original dot-key structure is removed.
    5.  **Overrides dictionary (`overrides_dict`)**: A dictionary where keys use dot-notation
        to specify the target setting. Values are parsed using `_parse_value`. These have the highest precedence.

    Nested dictionaries loaded from any source are automatically converted into `Config`
    objects, allowing chained dot-notation access (e.g., `cfg.section.subsection.key`).
    """

    def __init__(self,
                 # --- Configuration Sources ---
                 defaults: Optional[Dict[str, Any]] = None,
                 file_path: Optional[str] = None,
                 prefix: Optional[str] = None, # Prefix for environment variables
                 overrides_dict: Optional[Mapping[str, Any]] = None, # Dot-notation keys for final overrides
                 # --- Validation ---
                 mandatory: Optional[List[str]] = None, # List of required dot-notation keys
                 # --- .env File Handling ---
                 load_dotenv_file: bool = True, # Whether to search for and load a .env file
                 dotenv_path: Optional[str] = None, # Explicit path to a .env file
                 # --- Direct Initialization (low precedence) ---
                 *args, # Allow initializing with a dictionary, e.g., Config({'a': 1})
                 **kwargs): # Allow initializing with keyword args, e.g., Config(a=1)

        # --- Step 0: Load .env File (Conditional) ---
        # This loads into os.environ, making variables available for Step 1c
        if load_dotenv_file:
            self._load_dotenv_file(dotenv_path)


        # --- Step 1: Collect Data from Each Source ---
        # Use deepcopy to avoid modifying original input dicts
        # These should all be plain dictionaries at this stage.
        defaults_data = copy.deepcopy(defaults or {})
        log.debug(f"DEBUG [confy.__init__]: Collected defaults_data: {defaults_data}")

        args_kwargs_data = {}
        initial_data_arg = args[0] if args and isinstance(args[0], dict) else {}
        initial_data_kwarg = kwargs
        args_kwargs_data = copy.deepcopy(initial_data_arg)
        if initial_data_kwarg:
            # Merge kwargs into the copied args_data
            args_kwargs_data = deep_merge(args_kwargs_data, initial_data_kwarg)
        log.debug(f"DEBUG [confy.__init__]: Collected args_kwargs_data: {args_kwargs_data}")

        # Pass defaults_data to _load_config_file for potential TOML key promotion
        file_data = self._load_config_file(file_path, defaults_data)
        log.debug(f"DEBUG [confy.__init__]: Collected file_data: {file_data}")

        # Collect env vars into a structured dict (simple _ -> . conversion)
        env_data = self._collect_env_vars(prefix)
        log.debug(f"DEBUG [confy.__init__]: Collected env_data: {env_data}")

        overrides_data = self._structure_overrides(overrides_dict)
        log.debug(f"DEBUG [confy.__init__]: Collected overrides_data: {overrides_data}")


        # --- Step 2: Merge Collected Data Sequentially ---
        # Start with defaults
        final_merged_data = defaults_data
        log.debug(f"DEBUG [confy.__init__]: Initial merge state (defaults): {final_merged_data}")

        # Merge args/kwargs
        if args_kwargs_data:
            final_merged_data = deep_merge(final_merged_data, args_kwargs_data)
            log.debug(f"DEBUG [confy.__init__]: After merging args/kwargs: {final_merged_data}")

        # Merge file data
        if file_data:
            final_merged_data = deep_merge(final_merged_data, file_data)
            log.debug(f"DEBUG [confy.__init__]: After merging file data: {final_merged_data}")

        # Merge environment data
        if env_data:
            final_merged_data = deep_merge(final_merged_data, env_data)
            log.debug(f"DEBUG [confy.__init__]: After merging env data: {final_merged_data}")

        # Merge overrides data (highest precedence)
        if overrides_data:
            final_merged_data = deep_merge(final_merged_data, overrides_data)
            log.debug(f"DEBUG [confy.__init__]: After merging overrides data: {final_merged_data}")

        log.debug("DEBUG [confy.__init__]: Final merged data before super().__init__: %s", final_merged_data)


        # --- Step 3: Initialize Self and Wrap Nested Structures ---
        # Initialize the Config object with the *final*, fully merged dictionary.
        super().__init__(final_merged_data)
        log.debug("DEBUG [confy.__init__]: Initialized self with final merged data.")

        # Wrap nested dicts/lists *after* initialization is complete.
        self._wrap_nested_items(self)
        log.debug("DEBUG [confy.__init__]: Wrapped nested items in self.")

        # --- Step 4: Remap Environment Variable Keys (Post-Initialization) ---
        # Correct env var mappings like 'feature.flags.new.ui' to 'feature_flags.new_ui'
        # if the latter exists from defaults/file. Operates on the wrapped 'self'.
        if env_data: # Only run if environment variables were processed
            self._remap_env_keys_post_init(env_data)
            log.debug(f"DEBUG [confy.__init__]: After remapping env keys post-init: {self}")


        # --- Step 5: Validate Mandatory Keys ---
        if mandatory:
             self._validate_mandatory(mandatory)
             log.debug("DEBUG [confy.__init__]: Validated mandatory keys.")

        log.debug("DEBUG [confy.__init__]: Config initialization complete.")


    def _load_dotenv_file(self, dotenv_path: Optional[str]):
        """Loads .env file into os.environ if python-dotenv is available."""
        if not load_dotenv:
            # Check existence only if load_dotenv isn't None (i.e., import failed) and warn if found
            effective_dotenv_path = dotenv_path or ".env" # Simple check if find_dotenv not available
            exists = False
            try:
                if not dotenv_path and find_dotenv: effective_dotenv_path = find_dotenv(usecwd=True) or effective_dotenv_path
                exists = os.path.exists(effective_dotenv_path)
            except Exception: pass # Ignore errors checking existence
            if exists: log.warning("Warning: python-dotenv not installed, cannot load .env file found at %s.", effective_dotenv_path)
            # else: log.debug("DEBUG [confy._load_dotenv_file]: python-dotenv not installed, skipping .env load.")
            return

        try:
            # Use find_dotenv to locate the file if no explicit path is given
            actual_dotenv_path = dotenv_path or find_dotenv(usecwd=True) # find_dotenv searches cwd and parents
            if actual_dotenv_path and os.path.exists(actual_dotenv_path):
                dotenv_was_loaded = load_dotenv(dotenv_path=actual_dotenv_path, override=False)
                if dotenv_was_loaded: log.debug(f"DEBUG [confy._load_dotenv_file]: Loaded .env file from: {actual_dotenv_path}.")
                else: log.debug(f"DEBUG [confy._load_dotenv_file]: .env file found at {actual_dotenv_path} but did not load (all variables might already exist in env).")
            # else:
                # log.debug(f"DEBUG [confy._load_dotenv_file]: No .env file found to load (searched path: {dotenv_path or 'auto'}).")
        except Exception as e:
            log.warning(f"Warning: Failed during .env file loading (path: {dotenv_path or 'auto'}): {e}")


    def _load_config_file(self, file_path: Optional[str], defaults_data: Optional[Dict] = None) -> dict:
        """
        Loads and parses JSON or TOML config file.

        For TOML files, if a key within a top-level section matches a root-level
        key in defaults_data, it's promoted to the root of the loaded data.
        """
        if not file_path:
            return {}
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Config file not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        file_content = None
        try:
            if ext == '.toml':
                if not tomli: raise RuntimeError("tomli (or tomllib) is required for TOML support.")
                with open(file_path, mode='rb') as f: file_content = tomli.load(f)

                # --- TOML Key Promotion Logic ---
                if file_content and defaults_data:
                    root_default_keys = set(defaults_data.keys())
                    promoted_keys = set()
                    # Iterate through a copy of items to allow modification
                    for section_key, section_data in list(file_content.items()):
                        if isinstance(section_data, dict):
                            # Check keys within this section
                            section_keys = set(section_data.keys())
                            keys_to_promote = root_default_keys.intersection(section_keys)
                            for key_to_promote in keys_to_promote:
                                # Promote only if not already at root or promoted from another section
                                if key_to_promote not in file_content or key_to_promote in promoted_keys:
                                    log.debug(f"Promoting TOML key '{key_to_promote}' from section '[{section_key}]' to root.")
                                    file_content[key_to_promote] = section_data.pop(key_to_promote)
                                    promoted_keys.add(key_to_promote)
                                else:
                                     log.warning(f"Skipping promotion of TOML key '{key_to_promote}' from section '[{section_key}]' as it already exists at the root.")
                            # Clean up empty section if all keys were promoted
                            if not section_data:
                                 log.debug(f"Removing empty TOML section '[{section_key}]' after key promotion.")
                                 del file_content[section_key]
                # --- End TOML Key Promotion ---

            elif ext == '.json':
                with open(file_path, mode='r', encoding='utf-8') as f: file_content = json.load(f)
            else:
                raise ValueError(f"Unsupported config file type: {ext}")
        except Exception as e:
            raise RuntimeError(f"Error loading/parsing file {file_path}: {e}") from e

        # Return deepcopy to prevent modification of cached file content if reused
        return copy.deepcopy(file_content) if file_content else {}


    @staticmethod
    def _collect_env_vars(prefix: Optional[str]) -> dict:
        """
        Collects environment variables matching the prefix into a structured dictionary.
        Uses simple underscore-to-dot conversion. Values are parsed using _parse_value.
        Remapping based on existing structure happens later in __init__.
        """
        env_data = {}
        applied_count = 0
        prefix_match = ""
        # Normalize prefix: ensure it ends with '_' if not empty
        if prefix is not None:
            prefix = prefix.strip()
            if prefix: prefix_match = prefix.rstrip('_') + '_'
        plen = len(prefix_match)
        prefix_upper = prefix_match.upper() # Use uppercase for matching

        log.debug(f"DEBUG [confy._collect_env_vars]: Checking {len(os.environ)} env vars with prefix '{prefix}' (match pattern: '{prefix_upper}*')")
        for var, raw_value in os.environ.items():
            var_upper = var.upper() # Compare uppercase var name
            # Check if var starts with prefix (or if prefix is empty, consider all vars)
            should_process = False
            if prefix_upper and var_upper.startswith(prefix_upper):
                should_process = True
            elif not prefix_upper and prefix == "": # Handle prefix="" case (match all)
                should_process = True

            if should_process:
                 key_part = var[plen:] # Get the part after the prefix
                 # Simple conversion: lowercase, replace all underscores with dots
                 dot_key = key_part.lower().replace("_", ".")
                 # Skip if the resulting key is empty (e.g., prefix was the entire var name)
                 if not dot_key and prefix != "": continue

                 log.debug(f"DEBUG [confy._collect_env_vars]: Processing env var '{var}' -> dot_key '{dot_key}'")
                 val = _parse_value(raw_value) # Parse the value
                 try:
                     # Set using dot notation, creating intermediate dicts
                     set_by_dot(env_data, dot_key, val, create_missing=True)
                     applied_count += 1
                 except Exception as e:
                     log.error(f"Error processing environment variable '{var}' (key: '{dot_key}') into structure: {e}")
        log.debug(f"DEBUG [confy._collect_env_vars]: Collected {applied_count} env vars into dict structure: {env_data}")
        return env_data # Return the structured dict


    def _remap_env_keys_post_init(self, env_data: dict):
        """
        Remaps environment variable keys from dotted notation to underscore-separated notation
        for existing config keys, including nested default keys (e.g., feature_flags.new_ui).
        """
        flat_env_keys = self._flatten_keys(env_data)
        log.debug(f"DEBUG [confy._remap_env_keys_post_init]: Flat env keys: {flat_env_keys}")

        keys_to_remove = []
        # First, remap direct underscore matches
        for dot_key in flat_env_keys:
            if '.' not in dot_key:
                continue
            underscore_key = dot_key.replace('.', '_')
            if self.__contains__(underscore_key):
                try:
                    value_to_move = get_by_dot(self, dot_key)
                    target_val = self.get(underscore_key)
                    target_is_dict = isinstance(target_val, (dict, Config))
                    value_is_dict = isinstance(value_to_move, (dict, Config))
                    if target_is_dict and value_is_dict:
                        merged = deep_merge(get_by_dot(self, underscore_key), value_to_move)
                        set_by_dot(self, underscore_key, merged, create_missing=False)
                    else:
                        set_by_dot(self, underscore_key, value_to_move, create_missing=False)
                    keys_to_remove.append(dot_key)
                except Exception as e:
                    log.warning(f"Could not remap '{dot_key}' to '{underscore_key}': {e}")

        # Then, remap nested default keys: map first two segments to root and rest to a single nested key
        for dot_key in sorted(flat_env_keys, key=lambda k: k.count('.'), reverse=True):
            segments = dot_key.split('.')
            if len(segments) < 3:
                continue
            root = '_'.join(segments[:2])
            nested = '_'.join(segments[2:])
            candidate = f"{root}.{nested}"
            if self.__contains__(candidate):
                try:
                    value_to_move = get_by_dot(self, dot_key)
                    set_by_dot(self, candidate, value_to_move, create_missing=False)
                    keys_to_remove.append(dot_key)
                except Exception as e:
                    log.warning(f"Could not remap nested '{dot_key}' to '{candidate}': {e}")

        # Remove original dot-key entries
        if keys_to_remove:
            unique_keys = sorted(set(keys_to_remove), key=lambda k: k.count('.'), reverse=True)
            log.debug(f"DEBUG [confy._remap_env_keys_post_init]: Removing dot-keys: {unique_keys}")
            for key in unique_keys:
                parts = key.split('.')
                parent = self
                try:
                    for p in parts[:-1]:
                        parent = parent[p]
                    final = parts[-1]
                    if isinstance(parent, (dict, Config)) and final in parent:
                        del parent[final]
                except Exception:
                    pass

    @staticmethod
    def _flatten_keys(d: dict, prefix: str = "") -> list:
        """Helper to get a flat list of all dot-notation keys in a dict."""
        keys = []
        for k, v in d.items():
            new_key = f"{prefix}.{k}" if prefix else k
            keys.append(new_key)
            if isinstance(v, dict):
                keys.extend(Config._flatten_keys(v, new_key))
        return keys



    @staticmethod
    def _structure_overrides(overrides_dict: Optional[Mapping[str, Any]]) -> dict:
        """Converts flat overrides dict with dot-keys into a structured dict."""
        if not overrides_dict:
            return {}

        structured_overrides = {}
        for key, raw_val in overrides_dict.items():
             try:
                 # Parse the value from the overrides dict before setting
                 parsed_val = _parse_value(raw_val)
                 # Use create_missing=True for overrides
                 set_by_dot(structured_overrides, key, parsed_val, create_missing=True)
             except Exception as e:
                 log.error(f"Error processing override key '{key}': {e}")

        # Return deepcopy to prevent modification of input dict
        return copy.deepcopy(structured_overrides)


    @staticmethod
    def _wrap_nested_items(data: Union[Dict, List, 'Config']):
        """Recursively wraps nested dicts in Config objects *in-place*."""
        if isinstance(data, (dict, Config)): # Operate on dict or Config directly
            # Iterate over keys snapshot because we might modify the dict/Config
            for key in list(data.keys()):
                value = data[key]
                if isinstance(value, dict):
                    # Only wrap if it's not already a Config object
                    if not isinstance(value, Config):
                        data[key] = Config(value) # Wrap plain dict
                        # Recurse into the newly wrapped object
                        Config._wrap_nested_items(data[key])
                    else:
                        # If already a Config object, just recurse into it
                        # This ensures its children are also wrapped if necessary
                        Config._wrap_nested_items(value)
                elif isinstance(value, list):
                    # If the value is a list, recurse into the list
                    Config._wrap_nested_items(value) # Process list items
        elif isinstance(data, list):
            # Iterate over list indices
            for i, item in enumerate(data):
                if isinstance(item, dict):
                     # Only wrap if it's not already a Config object
                    if not isinstance(item, Config):
                        data[i] = Config(item) # Wrap plain dict in list
                        # Recurse into the newly wrapped object
                        Config._wrap_nested_items(data[i])
                    else:
                        # If already a Config object, just recurse into it
                        Config._wrap_nested_items(item)
                elif isinstance(item, list):
                    # If the item is a list, recurse into it
                    Config._wrap_nested_items(item)

    def _validate_mandatory(self, keys: List[str]):
        """Checks for mandatory keys using get_by_dot."""
        missing = []
        log.debug(f"DEBUG [confy._validate_mandatory]: Checking mandatory keys: {keys}")
        for k in keys:
            try: get_by_dot(self, k) # Attempt to retrieve the key
            except (KeyError, TypeError) as e:
                log.debug(f"DEBUG [confy._validate_mandatory]: Mandatory key '{k}' MISSING or path invalid. Error: {e}")
                missing.append(k)
        if missing: raise MissingMandatoryConfig(missing)

    # --- Attribute Access Magic Methods ---
    def __getattr__(self, name: str) -> Any:
        # Prevent access to private/magic methods via getattr
        if name.startswith('_'):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        try:
            # Retrieve item using standard dictionary access
            return self[name]
        except KeyError:
            # Raise AttributeError if key doesn't exist, standard behavior
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'") from None

    def __setattr__(self, name: str, value: Any):
        # Handle private attributes normally
        if name.startswith('_'):
            super().__setattr__(name, value)
            return

        # Wrap dictionaries and lists being assigned
        wrapped_value = value
        if isinstance(value, dict) and not isinstance(value, Config):
            # Wrap plain dicts into Config objects
            wrapped_value = Config(value)
            # Ensure nested items within the newly assigned dict are also wrapped
            self._wrap_nested_items(wrapped_value)
        elif isinstance(value, list):
            # Deep copy the list and wrap its contents recursively
            new_list = copy.deepcopy(value)
            self._wrap_nested_items(new_list) # Wrap items within the new list
            wrapped_value = new_list

        # Set the item using standard dictionary access
        self[name] = wrapped_value

    def __delattr__(self, name: str):
        # Prevent deletion of private/magic attributes
        if name.startswith('_'):
            raise AttributeError(f"Cannot delete private attribute: {name}")
        try:
            # Delete item using standard dictionary access
            del self[name]
        except KeyError:
            # Raise AttributeError if key doesn't exist
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'") from None

    # --- Dictionary-like Methods supporting dot-notation ---
    def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a value using dot-notation, returning default if not found.
        """
        try:
            # Use the helper function for robust nested access
            return get_by_dot(self, key)
        except (KeyError, TypeError):
            # Return the default value if the key path is invalid or not found
            return default

    def __contains__(self, key: Any) -> bool:
        """
        Check for key existence, supporting dot-notation for string keys.
        Avoids recursion by trying get_by_dot and catching exceptions.
        """
        # Use standard __contains__ for non-string keys or private keys
        if not isinstance(key, str) or key.startswith('_'):
            return super().__contains__(key)
        try:
            # Attempt to get the value using dot notation.
            # If successful, the key exists.
            get_by_dot(self, key)
            return True
        except (KeyError, TypeError):
            # If get_by_dot fails, the key path does not exist.
            return False

    # --- Utility Methods ---
    def as_dict(self) -> dict:
        """
        Return the configuration as a standard Python dictionary.

        Recursively converts nested Config objects back into plain dictionaries.
        """
        plain_dict = {}
        for key, value in self.items():
            if isinstance(value, Config):
                # Recursively convert nested Config objects
                plain_dict[key] = value.as_dict()
            elif isinstance(value, list):
                # Process lists: convert Config objects within lists
                plain_dict[key] = [
                    item.as_dict() if isinstance(item, Config) else copy.deepcopy(item)
                    for item in value
                ]
            else:
                # Deep copy other values to ensure independence
                plain_dict[key] = copy.deepcopy(value)
        return plain_dict

    # --- Standard Representation Methods ---
    def __repr__(self) -> str:
        # Provide a representation similar to a standard dict
        return f"{type(self).__name__}({super().__repr__()})"

    def __str__(self) -> str:
        """Return a JSON representation of the configuration."""
        try:
            # Use as_dict() to get the plain dictionary structure for serialization
            return json.dumps(self.as_dict(), indent=2)
        except Exception:
             # Fallback to standard repr if JSON serialization fails
            return repr(self)
