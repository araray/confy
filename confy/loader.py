# confy/loader.py
"""
confy.loader
------------

Core configuration loader using dictionary inheritance for robust attribute access.
Supports loading from defaults, JSON/TOML files, .env files, environment
variables, and override dictionaries.
Requires Python 3.10+.

Environment Variable Mapping Rules:
- After removing the optional prefix (e.g., `MYAPP_`), the remaining variable name
  is converted to lowercase.
- Single underscores (`_`) are typically converted to dots (`.`) to create nested keys
  (e.g., `DATABASE_HOST` -> `database.host`).
- Double underscores (`__`) are converted to a single underscore (`_`) within the key name,
  allowing underscores in the final configuration keys
  (e.g., `FEATURE_FLAGS__BETA_FEATURE` -> `feature_flags.beta_feature` if `feature_flags` exists,
  or `FEATURE__FLAG_NAME` -> `feature.flag_name`).
- The remapping logic attempts to match the resulting key structure against the
  existing keys in defaults and config files to ensure overrides land correctly.
  See `_remap_and_flatten_env_data` for detailed logic.
"""

import copy  # For deepcopy
import json
import logging
import os
from typing import Any, Dict, List, Mapping, Optional, Union

# Use tomli for reading TOML (works for Python 3.10+)
try:
    import tomli
except ImportError:
    try:
        import tomllib as tomli  # Python 3.11+
    except ImportError:
        tomli = None

# Import load_dotenv from python-dotenv
try:
    from dotenv import find_dotenv, load_dotenv  # Added find_dotenv for check
except ImportError:
    load_dotenv, find_dotenv = None, None

from .exceptions import MissingMandatoryConfig

log = logging.getLogger(__name__)  # Logger for confy loader

# --- Helper Functions ---


def deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
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
                merged[key] = value_updates  # Assign Config object directly
            else:
                merged[key] = copy.deepcopy(value_updates)
            # log.debug(f"deep_merge: Overwriting key '{key}' with value type {type(value_updates).__name__}")

    return merged


def set_by_dot(
    cfg: Union[dict[str, Any], "Config"],
    key: str,
    value: Any,
    create_missing: bool = True,
):
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
    parts = key.split(".")
    d = cfg  # Start traversal from the root dictionary/Config
    # Traverse the path up to the second-to-last part
    for i, p in enumerate(parts[:-1]):
        current_val = d.get(p)  # Use .get() for safe access on both dict/Config

        if not isinstance(current_val, (dict, Config)):  # Check if it's dict-like
            if not create_missing:
                if p not in d:
                    raise KeyError(f"Path segment '{p}' not found in key '{key}'")
                else:
                    raise TypeError(
                        f"Path segment '{p}' (type: {type(current_val).__name__}) in key '{key}' is not a dictionary."
                    )
            # If create_missing is True:
            if p in d:
                log.warning(
                    f"Warning: Overwriting non-dictionary key '{p}' (type: {type(current_val).__name__}) in path '{key}' during set_by_dot."
                )
            # Create a new dictionary (or Config if target is Config)
            # Ensure we create the right type (dict or Config) based on the container
            new_dict = Config({}) if isinstance(d, Config) else {}
            d[p] = new_dict
            current_val = new_dict  # Update current_val to the newly created dict
        # Move deeper into the dictionary structure
        d = current_val  # Use current_val which is guaranteed to be a dict/Config here

    # Set the value at the final key part
    final_key = parts[-1]
    if not create_missing and final_key not in d:
        # If the final key itself is missing and we are not creating.
        raise KeyError(f"Final key '{final_key}' not found in path '{key}'")

    # Wrap value if setting within a Config object and value is a dict
    if (
        isinstance(d, Config)
        and isinstance(value, dict)
        and not isinstance(value, Config)
    ):
        d[final_key] = Config(value)
    else:
        d[final_key] = value


def get_by_dot(cfg: Union[Mapping[str, Any], "Config"], key: str) -> Any:
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
    d = cfg  # Start traversal from the root
    parts = key.split(".")
    current_path_parts: list[
        str
    ] = []  # Keep track of the path traversed so far for error messages
    try:
        for i, p in enumerate(parts):
            current_path_parts.append(p)
            # Ensure the current level 'd' is a dictionary-like object before indexing
            # Check Mapping for dicts, Config for Config objects
            if not isinstance(d, (Mapping, Config)):
                current_path = ".".join(
                    current_path_parts[:-1]
                )  # Path up to the error point
                raise TypeError(
                    f"Cannot access key '{p}' on non-dictionary item at path '{current_path}' (item type: {type(d).__name__})"
                )

            # Access the next level using standard item access (works for both dict and Config).
            # This will raise KeyError if 'p' is not in 'd'.
            d = d[p]

        # Return the final value after successful traversal
        return d
    except KeyError as e:
        # If a key is not found during traversal
        missing_part = (
            e.args[0]
            if e.args
            else current_path_parts[-1]
            if current_path_parts
            else key
        )  # Get the missing key from the exception or last part
        found_path = ".".join(
            current_path_parts[:-1]
        )  # The valid path leading up to the missing part
        raise KeyError(
            f"Key path '{key}' not found (missing part: '{missing_part}' at path '{found_path}')"
        ) from None
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
    if lower_val == "true":
        # log.debug("DEBUG [_parse_value]: Parsed as True (boolean)")
        return True
    if lower_val == "false":
        # log.debug("DEBUG [_parse_value]: Parsed as False (boolean)")
        return False
    if lower_val == "null":
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
            if (
                (stripped_val.startswith("{") and stripped_val.endswith("}"))
                or (stripped_val.startswith("[") and stripped_val.endswith("]"))
                or (stripped_val.startswith('"') and stripped_val.endswith('"'))
            ):
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
        matching the specified `prefix` are processed:
           a) Collected into a nested dictionary (`_collect_env_vars`), filtering system
              variables if `prefix=""`. Uses `_` -> `.` and `__` -> `_` conversion.
           b) Remapped and flattened based on the structure of defaults/file data
              (`_remap_and_flatten_env_data`). This handles converting keys like
              `SECRETS_API_KEY` -> `secrets.api_key` if `secrets` exists, or
              `FEATURE_FLAGS__BETA_FEATURE` -> `feature_flags.beta_feature` based on context.
           c) Structured back into a nested dictionary (`_structure_overrides`).
           d) Merged into the main configuration.
    5.  **Overrides dictionary (`overrides_dict`)**: A dictionary where keys use dot-notation
        to specify the target setting. Values are parsed using `_parse_value`. These have the highest precedence.

    Nested dictionaries loaded from any source are automatically converted into `Config`
    objects, allowing chained dot-notation access (e.g., `cfg.section.subsection.key`).
    """

    def __init__(
        self,
        # --- Configuration Sources ---
        defaults: Optional[Dict[str, Any]] = None,
        file_path: Optional[str] = None,
        prefix: Optional[str] = None,  # Prefix for environment variables
        overrides_dict: Optional[
            Mapping[str, Any]
        ] = None,  # Dot-notation keys for final overrides
        # --- Validation ---
        mandatory: Optional[List[str]] = None,  # List of required dot-notation keys
        # --- .env File Handling ---
        load_dotenv_file: bool = True,  # Whether to search for and load a .env file
        dotenv_path: Optional[str] = None,  # Explicit path to a .env file
        # --- Direct Initialization (low precedence) ---
        *args,  # Allow initializing with a dictionary, e.g., Config({'a': 1})
        **kwargs,
    ):  # Allow initializing with keyword args, e.g., Config(a=1)

        # Store prefix and load_dotenv_file for later use in remapping
        self._prefix = prefix
        self._load_dotenv_file = load_dotenv_file

        # --- Step 0: Load .env File (Conditional) ---
        # This loads into os.environ, making variables available for Step 1d
        if self._load_dotenv_file:
            self._load_dotenv_file_action(dotenv_path)  # Renamed to avoid conflict

        # --- Step 1: Collect Base Data (Defaults, Args/Kwargs, File) ---
        defaults_data = copy.deepcopy(defaults or {})
        log.debug(f"DEBUG [confy.__init__]: Collected defaults_data: {defaults_data}")

        args_kwargs_data = {}
        initial_data_arg = args[0] if args and isinstance(args[0], dict) else {}
        initial_data_kwarg = kwargs
        args_kwargs_data = copy.deepcopy(initial_data_arg)
        if initial_data_kwarg:
            args_kwargs_data = deep_merge(args_kwargs_data, initial_data_kwarg)
        log.debug(
            f"DEBUG [confy.__init__]: Collected args_kwargs_data: {args_kwargs_data}"
        )

        file_data = self._load_config_file(file_path, defaults_data)
        log.debug(f"DEBUG [confy.__init__]: Collected file_data: {file_data}")

        # --- Step 2: Merge Base Data ---
        final_merged_data = defaults_data
        if args_kwargs_data:
            final_merged_data = deep_merge(final_merged_data, args_kwargs_data)
        if file_data:
            final_merged_data = deep_merge(final_merged_data, file_data)
        log.debug(
            f"DEBUG [confy.__init__]: After merging base data (defaults, args/kwargs, file): {final_merged_data}"
        )

        # --- Step 3: Process and Merge Environment Data ---
        nested_env_data = self._collect_env_vars(self._prefix)
        log.debug(
            f"DEBUG [confy.__init__]: Collected nested env_data: {nested_env_data}"
        )

        if nested_env_data:
            # Remap and flatten env data based on the structure of defaults and file data
            # Pass copies to avoid modification
            flat_remapped_env_data = self._remap_and_flatten_env_data(
                nested_env_data,
                copy.deepcopy(defaults_data),
                copy.deepcopy(file_data),
                self._prefix,  # Pass prefix
                self._load_dotenv_file,  # Pass load_dotenv_file flag
            )
            log.debug(
                f"DEBUG [confy.__init__]: Flat remapped env data: {flat_remapped_env_data}"
            )

            # Structure the remapped flat data
            structured_env_data = self._structure_overrides(flat_remapped_env_data)
            log.debug(
                f"DEBUG [confy.__init__]: Structured env data after remapping: {structured_env_data}"
            )

            # Merge the structured env data
            final_merged_data = deep_merge(final_merged_data, structured_env_data)
            log.debug(
                f"DEBUG [confy.__init__]: After merging remapped env data: {final_merged_data}"
            )

        # --- Step 4: Merge Explicit Overrides ---
        # Structure the overrides_dict passed to __init__
        structured_overrides_data = self._structure_overrides(overrides_dict)
        log.debug(
            f"DEBUG [confy.__init__]: Structured overrides data: {structured_overrides_data}"
        )
        if structured_overrides_data:
            final_merged_data = deep_merge(final_merged_data, structured_overrides_data)
            log.debug(
                f"DEBUG [confy.__init__]: After merging overrides data: {final_merged_data}"
            )

        log.debug(
            "DEBUG [confy.__init__]: Final merged data before super().__init__: %s",
            final_merged_data,
        )

        # --- Step 5: Initialize Self and Wrap Nested Structures ---
        super().__init__(final_merged_data)
        self._wrap_nested_items(self)
        log.debug("DEBUG [confy.__init__]: Wrapped nested items in self.")

        # --- Step 6: Validate Mandatory Keys ---
        if mandatory:
            self._validate_mandatory(mandatory)
            log.debug("DEBUG [confy.__init__]: Validated mandatory keys.")

        # --- NO Post-Initialization Remapping Step ---
        log.debug("DEBUG [confy.__init__]: Config initialization complete.")

    def _load_dotenv_file_action(self, dotenv_path: Optional[str]):  # Renamed method
        """Loads .env file into os.environ if python-dotenv is available."""
        if not load_dotenv:
            effective_dotenv_path = dotenv_path or ".env"
            exists = False
            try:
                if not dotenv_path and find_dotenv:
                    effective_dotenv_path = (
                        find_dotenv(usecwd=True) or effective_dotenv_path
                    )
                exists = os.path.exists(effective_dotenv_path)
            except Exception:
                pass
            if exists:
                log.warning(
                    "Warning: python-dotenv not installed, cannot load .env file found at %s.",
                    effective_dotenv_path,
                )
            return

        try:
            actual_dotenv_path = dotenv_path or (
                find_dotenv(usecwd=True) if find_dotenv else None
            )
            if actual_dotenv_path and os.path.exists(actual_dotenv_path):
                dotenv_was_loaded = load_dotenv(
                    dotenv_path=actual_dotenv_path, override=False
                )
                if dotenv_was_loaded:
                    log.debug(
                        f"DEBUG [confy._load_dotenv_file_action]: Loaded .env file from: {actual_dotenv_path}."
                    )
                else:
                    log.debug(
                        f"DEBUG [confy._load_dotenv_file_action]: .env file found at {actual_dotenv_path} but did not load (all variables might already exist in env)."
                    )
        except Exception as e:
            log.warning(
                f"Warning: Failed during .env file loading (path: {dotenv_path or 'auto'}): {e}"
            )

    def _load_config_file(
        self, file_path: Optional[str], defaults_data: Optional[Dict[str, Any]] = None
    ) -> dict[str, Any]:
        """
        Loads and parses JSON or TOML config file.
        Handles TOML key promotion based on defaults.
        """
        if not file_path:
            return {}
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Config file not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        file_content = None
        try:
            if ext == ".toml":
                if not tomli:
                    raise RuntimeError(
                        "tomli (or tomllib) is required for TOML support."
                    )
                with open(file_path, mode="rb") as f:
                    file_content = tomli.load(f)
                # --- TOML Key Promotion Logic ---
                if file_content and defaults_data:
                    root_default_keys = set(defaults_data.keys())
                    promoted_keys = set()
                    for section_key, section_data in list(file_content.items()):
                        if isinstance(section_data, dict):
                            section_keys = set(section_data.keys())
                            keys_to_promote = root_default_keys.intersection(
                                section_keys
                            )
                            for key_to_promote in keys_to_promote:
                                if (
                                    key_to_promote not in file_content
                                    or key_to_promote in promoted_keys
                                ):
                                    log.debug(
                                        f"Promoting TOML key '{key_to_promote}' from section '[{section_key}]' to root."
                                    )
                                    file_content[key_to_promote] = section_data.pop(
                                        key_to_promote
                                    )
                                    promoted_keys.add(key_to_promote)
                                else:
                                    log.warning(
                                        f"Skipping promotion of TOML key '{key_to_promote}' from section '[{section_key}]' as it already exists at the root."
                                    )
                            if not section_data:
                                log.debug(
                                    f"Removing empty TOML section '[{section_key}]' after key promotion."
                                )
                                del file_content[section_key]
                # --- End TOML Key Promotion ---
            elif ext == ".json":
                with open(file_path, mode="r", encoding="utf-8") as f:
                    file_content = json.load(f)
            else:
                raise ValueError(f"Unsupported config file type: {ext}")
        except Exception as e:
            raise RuntimeError(f"Error loading/parsing file {file_path}: {e}") from e
        return copy.deepcopy(file_content) if file_content else {}

    @staticmethod
    def _collect_env_vars(prefix: Optional[str]) -> dict[str, Any]:
        """
        Collects environment variables matching the prefix into a *nested* dictionary.
        Uses underscore-to-dot conversion for keys, respecting double underscores.
        Values are parsed. Filters common system variables if prefix is "".

        Mapping:
          - `PREFIX_A_B` -> `a.b`
          - `PREFIX_A__B` -> `a_b` (becomes `a_b` in the initial nested dict)
        """
        env_data = {}
        applied_count = 0
        prefix_match = ""
        if prefix is not None:
            prefix = prefix.strip()
            if prefix:
                prefix_match = prefix.rstrip("_") + "_"
        plen = len(prefix_match)
        prefix_upper = prefix_match.upper()

        # List of common system environment variable prefixes/names to exclude when prefix=""
        system_prefixes_or_names = [
            "XDG_",
            "ZSH_",
            "TERM_",
            "COLORTERM",
            "SSH_",
            "HOME",
            "PWD",
            "USER",
            "SHELL",
            "LANG",
            "LC_",
            "DISPLAY",
            "PATH",
            "_",
            "SHLVL",
            "OLDPWD",
            "EDITOR",
            "PAGER",
            "LESS",
            "VISUAL",
            "VIRTUAL_ENV",
            "WINDOWID",
            "HOSTTYPE",
            "OSTYPE",
            "MACHTYPE",
            "LS_",
            "PYTHONUTF8",
            "PYTHONPATH",
            "PS1",
            "PS2",
            "WINDOWPATH",
            "QTWEBENGINE_",
            "QT_",
            "MOZ_",
            "GDK_",
            "GTK_",
            "BROWSER",
            "MAIL",
            "LOGNAME",
            "USERNAME",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "PROMPT",
            "HOSTNAME",
            "DOMAINNAME",
            "MANPATH",
        ]
        system_prefixes_or_names_upper = [s.upper() for s in system_prefixes_or_names]

        log.debug(
            f"DEBUG [confy._collect_env_vars]: Checking {len(os.environ)} env vars with prefix '{prefix}' (match pattern: '{prefix_upper}*')"
        )
        for var, raw_value in os.environ.items():
            var_upper = var.upper()
            should_process = False

            if prefix_upper and var_upper.startswith(prefix_upper):
                should_process = True
            elif not prefix_upper and prefix == "":  # Handle prefix=""
                is_system_var = False
                for sys_prefix in system_prefixes_or_names_upper:
                    if var_upper.startswith(sys_prefix):
                        is_system_var = True
                        break
                if not is_system_var:
                    should_process = True
                else:
                    log.debug(
                        f"Skipping system environment variable '{var}' with empty prefix"
                    )

            if should_process:
                key_part = var[plen:]  # Original key part after prefix removal
                if not key_part and prefix != "":
                    continue  # Skip if only prefix matched

                # Convert to lowercase and handle underscores: __ -> _, _ -> .
                # Replace double first, then single to avoid issues with triple underscores
                dot_key = (
                    key_part.lower()
                    .replace("__", "#TEMP#")
                    .replace("_", ".")
                    .replace("#TEMP#", "_")
                )

                log.debug(
                    f"DEBUG [confy._collect_env_vars]: Processing env var '{var}' -> dot_key '{dot_key}' (key_part: '{key_part}')"
                )
                val = _parse_value(raw_value)
                try:
                    set_by_dot(env_data, dot_key, val, create_missing=True)
                    applied_count += 1
                except Exception as e:
                    log.error(
                        f"Error processing environment variable '{var}' (key: '{dot_key}') into structure: {e}"
                    )
        log.debug(
            f"DEBUG [confy._collect_env_vars]: Collected {applied_count} relevant env vars into nested dict structure: {env_data}"
        )
        return env_data

    @staticmethod
    def _remap_and_flatten_env_data(
        nested_env_data: dict[str, Any],
        defaults_data: dict[str, Any],
        file_data: dict[str, Any],
        prefix: Optional[str],
        load_dotenv_file: bool,
    ) -> dict[str, Any]:
        """
        Remaps and flattens environment variable keys based on defaults/file structure.
        Handles base keys with underscores and applies context-aware fallback logic.

        Args:
            nested_env_data: The nested dictionary from _collect_env_vars.
            defaults_data: The defaults dictionary.
            file_data: The dictionary loaded from the config file.
            prefix: The prefix used for environment variables.
            load_dotenv_file: Flag indicating if .env file loading was attempted.

        Returns:
            A flat dictionary with remapped dot-notation keys ready for structuring.
            e.g., {'database.host': 'val', 'added_by_env': 'val', 'secrets.api_key': 'val'}
        """
        flat_remapped_env_data = {}

        # Combine defaults and file for checking existence (file overrides defaults)
        base_config_check = deep_merge(defaults_data, file_data)

        # Get a flat list of all valid keys from the base config for efficient lookup
        valid_base_keys = Config._flatten_keys(base_config_check)

        # Helper to get flat items (dot_key, value)
        def _get_flat_items(d, prefix=""):
            items = []
            for k, v in d.items():
                new_key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    items.extend(_get_flat_items(v, new_key))
                else:
                    items.append((new_key, v))
            return items

        flat_env_items = _get_flat_items(nested_env_data)
        log.debug(
            f"DEBUG [_remap_and_flatten_env_data]: Flat env items before remapping: {flat_env_items}"
        )
        log.debug(
            f"DEBUG [_remap_and_flatten_env_data]: Valid base keys for remapping check: {valid_base_keys}"
        )

        # Process deepest keys first to ensure correct precedence if keys overlap after remapping
        for dot_key, value in sorted(
            flat_env_items, key=lambda item: item[0].count("."), reverse=True
        ):
            parts = dot_key.split(".")
            remapped_key = None

            # --- BEGIN FIX ---
            # Heuristic 0: Handle base keys that themselves contain underscores
            # e.g., dot_key = "feature.flags.beta.feature" from MYAPP_FEATURE_FLAGS_BETA_FEATURE
            #       valid_base_keys contains "feature_flags.beta_feature"
            # We need to map "feature.flags.beta.feature" -> "feature_flags.beta_feature"
            reconstructed_flat = dot_key.replace(
                ".", "_"
            )  # -> "feature_flags_beta_feature"
            if "_" in reconstructed_flat:
                # Split only on the *first* underscore to find potential base key
                root, rest = reconstructed_flat.split(
                    "_", 1
                )  # -> ("feature_flags", "beta_feature")
                candidate = f"{root}.{rest}"  # -> "feature_flags.beta_feature"
                if candidate in valid_base_keys:
                    remapped_key = candidate
                    log.debug(
                        f"Heuristic remapping '{dot_key}' -> '{remapped_key}' "
                        "based on underscore-containing base key."
                    )
                    # If heuristic matches, use it and skip other attempts
                    if remapped_key not in flat_remapped_env_data:
                        flat_remapped_env_data[remapped_key] = value
                        log.debug(
                            f"Added to flat remapped data (heuristic): '{remapped_key}': {value!r}"
                        )
                    else:
                        log.warning(
                            f"Skipping assignment for '{dot_key}' -> '{remapped_key}' (heuristic) as target key already set."
                        )
                    continue  # Go to the next env var item

            # Attempt 1: Check if the key reconstructed with underscores exists in base config
            # (Original logic, now Attempt 1) - Use reconstructed_flat from above
            if reconstructed_flat in valid_base_keys:
                remapped_key = reconstructed_flat
                log.debug(
                    f"Remapping '{dot_key}' to existing exact base config key '{remapped_key}'."
                )

            # Attempt 2: If not found, try finding the longest prefix that matches a base config key
            # (Original logic, now Attempt 2)
            if not remapped_key:
                for i in range(len(parts) - 1, 0, -1):
                    potential_root_key = ".".join(parts[:i])
                    rest_parts = parts[i:]

                    # Check if this potential_root_key exists as a complete key in the base config
                    if potential_root_key in valid_base_keys:
                        # Check if the target is actually a dictionary in the base config
                        try:
                            target_in_base = get_by_dot(
                                base_config_check, potential_root_key
                            )
                            if isinstance(target_in_base, dict):
                                # If it exists and is a dict, construct the remapped key
                                # Join rest_parts with underscore to preserve original structure from env var
                                remapped_key = (
                                    f"{potential_root_key}.{'_'.join(rest_parts)}"
                                )
                                log.debug(
                                    f"Remapping '{dot_key}' to '{remapped_key}' based on existing base config dict key '{potential_root_key}'."
                                )
                                break  # Found the longest matching prefix
                        except (KeyError, TypeError):
                            pass  # Should not happen if key is in valid_base_keys, but check defensively
            # --- END FIX ---

            # --- Determine final key ---
            if remapped_key:
                # We found a remapping based on defaults/file structure
                final_key = remapped_key
            else:
                # --- Apply context-aware fallback logic ---
                if prefix == "":
                    # Empty-prefix: treat every original underscore as a nesting dot.
                    final_key = dot_key
                    log.debug(
                        f"No remap target for '{dot_key}' (empty prefix). Falling back to '{final_key}'."
                    )
                else:
                    # Prefix is not empty
                    if load_dotenv_file:
                        # .env-loaded variables: Use the original dot_key directly if no remap found.
                        final_key = dot_key
                        log.debug(
                            f"No remap target for '{dot_key}' (.env mode). Falling back to original dot key: '{final_key}'."
                        )
                    else:
                        # Real env vars (no-dotenv): preserve all original underscores as one flat key
                        # Reconstruct by replacing dots back to underscores
                        final_key = dot_key.replace(".", "_")  # e.g., added_by_env
                        log.debug(
                            f"No remap target for '{dot_key}' (direct env mode). Falling back to flat key: '{final_key}'."
                        )

            # --- Add to the flat output dictionary ---
            # Check for conflicts: If final_key already exists, the deeper key (processed first) wins.
            if final_key not in flat_remapped_env_data:
                flat_remapped_env_data[final_key] = value
                log.debug(f"Added to flat remapped data: '{final_key}': {value!r}")
            else:
                log.warning(
                    f"Skipping assignment for '{dot_key}' -> '{final_key}' as target key already set by a deeper source or previous mapping."
                )

        log.debug(
            f"DEBUG [_remap_and_flatten_env_data]: Final flat remapped env data: {flat_remapped_env_data}"
        )
        return flat_remapped_env_data

    @staticmethod
    def _flatten_keys(
        d: Union[dict[str, Any], "Config"], prefix: str = ""
    ) -> list[str]:
        """Static helper to get a flat list of all dot-notation keys in a dict or Config."""
        keys = []
        # Use items() which works for both dict and Config
        for k, v in d.items():
            new_key = f"{prefix}.{k}" if prefix else k
            keys.append(new_key)
            # Check if value is dict-like (dict or Config)
            if isinstance(v, (dict, Config)):
                # Pass the actual object 'v' for recursion
                keys.extend(Config._flatten_keys(v, new_key))
        return keys

    @staticmethod
    def _structure_overrides(
        overrides_dict: Optional[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """
        Converts flat overrides dict with dot-keys into a structured nested dict.
        Values are parsed using _parse_value.
        """
        if not overrides_dict:
            return {}

        structured_overrides = {}
        # Sort keys to ensure parent keys are processed before children if structure allows
        # Although set_by_dot handles creation, sorting might be slightly safer conceptually.
        sorted_keys = sorted(overrides_dict.keys())

        for key in sorted_keys:
            raw_val = overrides_dict[key]
            try:
                # Parse the value from the overrides dict before setting
                # Note: _parse_value is already called in _collect_env_vars,
                # but calling it again here handles the case for the explicit overrides_dict.
                # It's idempotent for non-string types.
                parsed_val = _parse_value(raw_val)
                # Use create_missing=True for overrides
                set_by_dot(structured_overrides, key, parsed_val, create_missing=True)
            except Exception as e:
                log.error(f"Error processing override key '{key}': {e}")

        # Return deepcopy to prevent modification of input dict (though structure is new)
        return copy.deepcopy(structured_overrides)

    @staticmethod
    def _wrap_nested_items(data: Union[Dict[str, Any], List[Any], "Config"]):
        """Recursively wraps nested dicts in Config objects *in-place*."""
        if isinstance(data, (dict, Config)):  # Operate on dict or Config directly
            for key in list(data.keys()):  # Iterate over keys snapshot
                value = data[key]
                if isinstance(value, dict):
                    if not isinstance(value, Config):
                        data[key] = Config(value)
                    Config._wrap_nested_items(data[key])  # Recurse into dict/Config
                elif isinstance(value, list):
                    Config._wrap_nested_items(value)  # Recurse into list
        elif isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, dict):
                    if not isinstance(item, Config):
                        data[i] = Config(item)
                    Config._wrap_nested_items(
                        data[i]
                    )  # Recurse into dict/Config in list
                elif isinstance(item, list):
                    Config._wrap_nested_items(item)  # Recurse into list in list

    def _validate_mandatory(self, keys: List[str]):
        """Checks for mandatory keys using get_by_dot."""
        missing = []
        log.debug(f"DEBUG [confy._validate_mandatory]: Checking mandatory keys: {keys}")
        for k in keys:
            try:
                get_by_dot(self, k)  # Attempt to retrieve the key
            except (KeyError, TypeError) as e:
                log.debug(
                    f"DEBUG [confy._validate_mandatory]: Mandatory key '{k}' MISSING or path invalid. Error: {e}"
                )
                missing.append(k)
        if missing:
            raise MissingMandatoryConfig(missing)

    # --- Attribute Access Magic Methods ---
    def __getattr__(self, name: str) -> Any:
        # Store internal state with leading underscore
        if name == "_prefix" or name == "_load_dotenv_file":
            return self.__dict__.get(name)  # Access directly from instance dict
        if name.startswith("_"):
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )
        try:
            return self[name]
        except KeyError:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            ) from None

    def __setattr__(self, name: str, value: Any):
        # Store internal state with leading underscore
        if name == "_prefix" or name == "_load_dotenv_file":
            self.__dict__[name] = value  # Store directly in instance dict
            return
        if name.startswith("_"):
            super().__setattr__(name, value)
            return
        wrapped_value = value
        if isinstance(value, dict) and not isinstance(value, Config):
            wrapped_value = Config(value)
            self._wrap_nested_items(wrapped_value)
        elif isinstance(value, list):
            new_list = copy.deepcopy(value)
            self._wrap_nested_items(new_list)
            wrapped_value = new_list
        self[name] = wrapped_value

    def __delattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(f"Cannot delete private attribute: {name}")
        try:
            del self[name]
        except KeyError:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            ) from None

    # --- Dictionary-like Methods supporting dot-notation ---
    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value using dot-notation, returning default if not found."""
        try:
            return get_by_dot(self, key)
        except (KeyError, TypeError):
            return default

    def __contains__(self, key: Any) -> bool:
        """Check for key existence, supporting dot-notation for string keys."""
        if not isinstance(key, str) or key.startswith("_"):
            return super().__contains__(key)
        try:
            get_by_dot(self, key)
            return True
        except (KeyError, TypeError):
            return False

    # --- Utility Methods ---
    def as_dict(self) -> dict[str, Any]:
        """Return the configuration as a standard Python dictionary."""
        plain_dict = {}
        for key, value in self.items():
            if isinstance(value, Config):
                plain_dict[key] = value.as_dict()
            elif isinstance(value, list):
                plain_dict[key] = [
                    item.as_dict() if isinstance(item, Config) else copy.deepcopy(item)
                    for item in value
                ]
            else:
                plain_dict[key] = copy.deepcopy(value)
        return plain_dict

    # --- Standard Representation Methods ---
    def __repr__(self) -> str:
        return f"{type(self).__name__}({super().__repr__()})"

    def __str__(self) -> str:
        """Return a JSON representation of the configuration."""
        try:
            return json.dumps(self.as_dict(), indent=2)
        except Exception:
            return repr(self)
