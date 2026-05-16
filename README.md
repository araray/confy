# confy

**confy** is a minimal, flexible Python configuration library (requiring **Python 3.10+**) and accompanying CLI tool. It simplifies configuration management by providing a unified way to:

- Load configuration from **JSON** & **TOML** files.
- Automatically load settings from **`.env`** files (using `python-dotenv`).
- Access settings intuitively via **dot-notation** (e.g., `cfg.database.host`).
- Define **default values** to ensure settings always have a fallback.
- Enforce **mandatory** configuration keys, raising errors if they are missing.
- Override any setting through **environment variables**, supporting prefixes (e.g., `MYAPP_DATABASE_PORT=5432`). See [Environment Overrides Explained](#environment-overrides-explained) for details on underscore mapping.
- Apply final overrides using a standard Python **dictionary**, ideal for integrating with command-line argument parsers like `argparse` or `click`.
- Inspect (`get`, `dump`, `search`, `exists`) and **mutate** (`set`, `convert`) configuration files directly from the command line using the `confy` tool.

---

## Loading Precedence

`confy` applies configuration sources in a specific, layered order. Each subsequent layer overrides values from the previous layers if keys conflict:

1.  **Defaults**: The dictionary provided to `Config(defaults=...)`. This forms the base layer.
2.  **Config File**: Values loaded from the file specified by `Config(file_path=...)` (supports `.json` and `.toml`).
3.  **`.env` File**: Variables loaded from a `.env` file into the environment using `python-dotenv`. By default, `confy` looks for `.env` in the current or parent directories. *Important:* `python-dotenv` (and thus `confy`) **does not override** environment variables that *already exist* when the `.env` file is loaded.
4.  **Environment Variables**: System environment variables, potentially filtered and mapped using `Config(prefix=...)`. These *will* override variables loaded from the `.env` file if they share the same name (after prefix mapping and remapping).
5.  **Overrides Dictionary**: The dictionary provided to `Config(overrides_dict=...)`. This is the final layer and takes the highest precedence.

---

## Table of Contents

1.  [Features](#features)
2.  [Installation](#installation)
3.  [Quickstart](#quickstart)
4.  [API Reference](#api-reference)
    -   [`Config` class](#config-class)
    -   [Argparse integration](#argparse-integration)
5.  [CLI Usage](#cli-usage)
    -   [Global options](#global-options)
    -   [Subcommands](#subcommands)
6.  [Advanced Usage](#advanced-usage)
    -   [Environment Overrides Explained](#environment-overrides-explained)
    -   [`.env` File Handling Details](#env-file-handling-details)
    -   [Chaining Multiple Sources](#chaining-multiple-sources)
    -   [Error Handling Strategies](#error-handling-strategies)
7.  [Upcoming features](#upcoming-features)
8.  [Testing](#testing)
9.  [Contributing](#contributing)
10. [License](#license)

---

## Features

-   **Multiple Sources**: Load from defaults, JSON, TOML (using `tomli`/`tomli-w`), `.env` files, environment variables, and Python dictionaries.
-   **Clear Precedence**: Predictable and well-defined override behavior across all configuration sources.
-   **Dot-Notation Access**: Read and write configuration values using natural attribute access (`cfg.section.key`). Nested dictionaries are automatically converted for chained access.
-   **Defaults & Validation**: Easily define default settings and specify mandatory keys (using dot-notation) to ensure essential configurations are present, raising `MissingMandatoryConfig` otherwise.
-   **Environment Overrides**: Override any setting using prefixed environment variables (e.g., `APP_CONF_DB_PORT=5432`). Variable names after the prefix are converted to lowercase and mapped to configuration keys, respecting underscores (see [Environment Overrides Explained](#environment-overrides-explained)).
-   **`.env` Support**: Automatically finds and loads variables from `.env` files into the process environment via `python-dotenv`, making local development setup easier. Configurable via constructor arguments.
-   **CLI Integration**: Seamlessly integrate with argument parsers (like `argparse` or `click`) by passing parsed arguments as the final `overrides_dict`. Includes an optional `argparse` helper.
-   **Powerful CLI Tool**: A `click`-based `confy` command allows you to inspect (`get`, `dump`, `search`, `exists`) and modify (`set`, `convert`) configuration files directly. Useful for scripting and diagnostics.
-   **Modern Tooling**: Uses `tomli` for reading TOML files and `tomli-w` for writing TOML files, ensuring compatibility with TOML v1.0.0 specification. **Requires Python 3.10+**.
-   **Basic Type Handling**: Attempts to parse environment variables and dictionary override values as JSON to preserve basic types like booleans, numbers, and strings (e.g., `export MYAPP_FLAG=true` is parsed as `True`). Falls back to string if JSON parsing fails.

---

## Installation

**Requires Python 3.10 or later.**

Install `confy` and its dependencies using pip:

```bash
pip install confy
````

Alternatively, to install directly from the source code:

```bash
git clone https://github.com/araray/confy.git
cd confy
pip install .
```

This installs both the Python library (`import confy`) and the `confy` command-line tool.

-----

## Quickstart

Here's a typical usage pattern within a Python application:

```python
# main_app.py
import os
import logging
from confy.loader import Config
from confy.exceptions import MissingMandatoryConfig

# Optional: Configure logging to see confy's internal debug messages
# logging.basicConfig(level=logging.DEBUG, format='%(levelname)s:%(name)s:%(message)s')

# 1. Define Defaults & Mandatory Keys
# These form the base layer and specify required settings.
defaults = {
    "database": {"host": "localhost", "port": 5432, "user": "guest"},
    "logging": {"level": "INFO", "format": "default"},
    "feature_flags": {"new_dashboard": False}
}
# Use dot-notation for mandatory keys, even nested ones.
mandatory = ["database.host", "database.port", "database.user", "logging.level"]

# 2. Prepare Overrides (e.g., from command-line arguments)
# This dictionary provides the highest precedence overrides.
# You might populate this using argparse, click, or another CLI parser.
cli_overrides = {
    "database.port": 5433,      # Override default/file/env port
    "logging.level": "DEBUG",   # Override default/file/env level
    "feature_flags.new_dashboard": True # Enable a feature flag via CLI
}

# 3. Initialize the Config Object
# confy automatically looks for and loads a '.env' file by default.
try:
    cfg = Config(
        # Specify a config file (optional). Supports .json and .toml.
        file_path="config.toml", # Example: 'config.json' or 'conf/app_settings.toml'

        # Specify a prefix for environment variable overrides (optional).
        prefix="MYAPP", # Looks for MYAPP_DATABASE_HOST, MYAPP_LOGGING_LEVEL etc.

        # Pass the defaults and mandatory keys defined above.
        defaults=defaults,
        mandatory=mandatory,

        # Pass the dictionary of overrides (e.g., from CLI args).
        overrides_dict=cli_overrides,

        # --- Optional .env controls ---
        # Disable automatic .env loading if needed:
        # load_dotenv_file=False,
        # Specify a custom path for the .env file:
        # dotenv_path='/etc/secrets/app.env'
    )
    print("Configuration loaded successfully!")
    # logging.debug(f"Final configuration: {cfg.as_dict()}") # See the merged result

except MissingMandatoryConfig as e:
    logging.error(f"Configuration Error: Missing required keys: {e.missing_keys}")
    print(f"Configuration Error: Missing required keys: {e.missing_keys}")
    exit(1)
except FileNotFoundError as e:
    logging.warning(f"Configuration Warning: Config file not found: {e}. Using defaults/env/overrides.")
    # Decide if this is fatal or acceptable based on your application's needs.
    # exit(1)
except Exception as e:
    logging.exception("An unexpected error occurred during configuration loading.")
    print(f"An unexpected error occurred during configuration loading: {e}")
    exit(1)


# 4. Access Settings via Dot Notation
# Access is intuitive and works for nested structures.
print(f"Database Host: {cfg.database.host}")
print(f"Database Port: {cfg.database.port}") # Will be 5433 due to cli_overrides
print(f"Database User: {cfg.database.user}") # Could come from defaults, file, or env
print(f"Logging Level: {cfg.logging.level}") # Will be DEBUG due to cli_overrides
print(f"Logging Format: {cfg.logging.format}") # Will be 'default' from defaults
print(f"New Dashboard Enabled: {cfg.feature_flags.new_dashboard}") # True due to cli_overrides

# Use .get() for optional settings with a fallback default.
# This is safer than direct access if a key might not exist at all.
timeout = cfg.get("network.timeout", 30) # Provides 30 if 'network.timeout' isn't set anywhere
print(f"Network Timeout: {timeout}")

# Check for key existence using 'in'. Works with dot-notation for nested keys.
if "secrets.api_key" in cfg:
    print(f"API Key found: {cfg.secrets.api_key}")
else:
    print("API Key is not configured.")

# Get the entire configuration as a standard Python dictionary.
# Useful for debugging, serialization, or passing to other libraries.
config_dict = cfg.as_dict()
# import json
# print(json.dumps(config_dict, indent=2))

```

**Example `config.toml`:**

```toml
# config.toml - Example configuration file

[database]
host = "prod.db.example.com" # Overrides default host
user = "prod_user"           # Overrides default user
# Port is not specified here, will use default (5432) unless overridden elsewhere

[logging]
level = "WARNING" # Overrides default "INFO", but can be overridden by env or cli_overrides

[feature_flags]
new_dashboard = false # Overrides default, but can be overridden by cli_overrides
```

**Example `.env` file:**

```dotenv
# .env file - Loaded into environment variables before explicit env vars are checked

# These variables need the correct prefix ('MYAPP_' in the Quickstart example)
# to be picked up by confy's environment variable loading step.
MYAPP_DATABASE_USER=env_db_user # Overrides user from config.toml
MYAPP_SECRETS_API_KEY="dotenv_abc123xyz" # Adds a new key

# This variable will NOT override an existing environment variable named 'MYAPP_LOGGING_LEVEL'
# if one was already set before the script ran.
MYAPP_LOGGING_LEVEL=INFO

# Example using double underscore for underscore in final key
MYAPP_FEATURE_FLAGS__BETA_FEATURE=true # -> feature_flags.beta_feature

# Variables without the prefix will be loaded into the environment but ignored by confy's
# prefix-based loading mechanism unless prefix is None or empty.
OTHER_ENV_VAR=some_other_value
```

-----

## API Reference

### `Config` class

The core class for loading and accessing configuration. Found in `confy/loader.py`.

```python
from confy.loader import Config

cfg = Config(
    # --- File Loading ---
    file_path: str = None,          # Path to the primary configuration file (.json or .toml).
                                    # If None, no file is loaded in this step.

    # --- Environment Loading ---
    prefix: str = None,             # Case-insensitive prefix for environment variables.
                                    # E.g., "APP" matches "APP_DB_HOST", "app_db_port".
                                    # If None or "", all non-system env vars are considered.
    load_dotenv_file: bool = True,  # Automatically search for and load a `.env` file?
    dotenv_path: str = None,        # Explicit path to a specific `.env` file. Overrides search.

    # --- Overrides & Defaults ---
    overrides_dict: Mapping[str, object] = None, # Dictionary of final overrides {'dot.key': value}.
                                                # Applied last with highest precedence.
    defaults: dict = None,          # Dictionary of default configuration values.
                                    # Applied first with lowest precedence.
                                    # NOTE (I-19): the dict is deep-copied internally
                                    # before merging, so mutations to your original
                                    # `defaults` dict after the Config is built do NOT
                                    # leak into the configuration, and vice versa.

    # --- Validation ---
    mandatory: list[str] = None,    # List of dot-notation keys that MUST have a value
                                    # after all sources are merged. Raises MissingMandatoryConfig if not found.

    # --- Env-var Remap Fallback (v0.4.1, I-05) ---
    env_remap_fallback: str = "auto",
        # Controls the fallback shape used when an env-var key cannot be
        # remapped against defaults/file structure:
        #   "auto"   — historical behavior, tied to load_dotenv_file:
        #              nested when True, flat when False.
        #   "nested" — always preserve the dot form (e.g. env.only).
        #   "flat"   — always collapse to the underscore form (e.g.
        #              env_only). Recommended for callers that don't
        #              want the .env switch to silently restructure
        #              their env-only keys.

    # --- Multi-File & App Collections (v0.4.0) ---
    file_paths: list[str | tuple[str, str]] = None,
        # Load multiple config files in order (later files override earlier ones).
        # Each entry is either a plain path string or a (path, namespace) tuple.
        # Tuple form nests the file's contents under the given namespace key:
        #   file_paths=[("semantiscan.toml", "semantiscan")]
        # loads semantiscan.toml contents into cfg.semantiscan.*.
        # If both file_path and file_paths are given, file_path is loaded first.

    app_defaults: dict[str, dict] = None,
        # Per-application default configs. Keys are app names (top-level namespaces),
        # values are default config dicts. Merged before file loading (lowest precedence).
        # Example: app_defaults={"myapp": {"debug": False, "port": 8080}}

    app_prefixes: dict[str, str] = None,
        # Per-application environment variable prefixes. Routes env vars with
        # app-specific prefixes to the correct namespace in the config.
        # Example: app_prefixes={"semantiscan": "SEMANTISCAN"}
        # makes SEMANTISCAN_CHUNKING__CHUNK_SIZE set cfg.semantiscan.chunking.chunk_size.

    # --- Provenance Tracking (v0.4.0) ---
    track_provenance: bool = False,
        # When True, records the source of every config value during merging.
        # Use cfg.provenance("key") to see where a value came from.
        # Disabled by default for zero overhead.
)
```

  - **Initialization**: Creates a configuration object by merging all specified sources according to the defined [precedence rules](#loading-precedence). Nested dictionaries within the sources are automatically converted into `Config` objects, enabling chained dot-notation access.
  - **Attribute Access**: Provides intuitive access to configuration values using dot notation (e.g., `cfg.section.key`). This works recursively for nested sections. It supports getting values, setting new values (`cfg.section.key = new_value`), and deleting keys (`del cfg.section.key`). Setting a dictionary value automatically wraps it in a `Config` object.
  - **Dictionary-like Behavior**: Inherits from `dict`, so standard dictionary methods like `get(key, default)`, `items()`, `keys()`, `values()` are available. The `get()` and `in` operations also support dot-notation for string keys (e.g., `cfg.get('database.host')`, `'logging.level' in cfg`).
  - **`as_dict()`**: Returns the fully resolved configuration as a standard Python dictionary. This recursively converts any nested `Config` objects back into plain dictionaries, making the result suitable for serialization (e.g., to JSON) or for passing to functions expecting standard dicts.
  - **`app(name)`** *(v0.4.0; behavior documented under I-18)*: Access an application's namespaced configuration. Returns the `Config` sub-object for the given namespace (e.g., `cfg.app("semantiscan").chunking.chunk_size`). Returns an empty `Config()` for unknown names — never raises. **Important**: if the requested namespace is missing, calling `cfg.app(name)` **wraps in place** — it side-effectfully writes an empty `Config()` under `cfg[name]` (so subsequent `name in cfg` returns True). This is intentional, to make the returned sub-object writable and mergeable, but callers who want pure read-only inspection should use `cfg.get(name, {})` instead.
  - **`provenance(key)`** *(v0.4.0)*: When `track_provenance=True`, returns a `ProvenanceEntry` showing where the current value of a dot-notation key came from (e.g., `"file:config.toml"`, `"env:MYAPP_*"`, `"defaults"`). Returns `None` if tracking is disabled.
  - **`provenance_history(key)`** *(v0.4.0)*: Returns the full override chain for a key as a list of `ProvenanceEntry` (oldest first). Shows how a value was set and successively overridden across sources.
  - **`provenance_dump()`** *(v0.4.0)*: Returns a `{key: source}` dict for all tracked keys. Useful for debugging entire config state.
  - **Error Handling**:
      - Raises `confy.exceptions.MissingMandatoryConfig` if any key listed in `mandatory` is not found after merging all sources. The exception object contains a `missing_keys` attribute (a list of the missing keys).
      - Raises `FileNotFoundError` if `file_path` or `dotenv_path` (if specified) points to a non-existent file.
      - Raises `RuntimeError` wrapping underlying errors (like `json.JSONDecodeError` or `tomli.TOMLDecodeError`) if a configuration file (`file_path` or `--defaults` in CLI) is malformed or cannot be parsed.
      - Raises `ValueError` if `env_remap_fallback` is not one of `"auto"`, `"nested"`, `"flat"`.

#### Reserved attribute names (I-20)

Because `Config` inherits from `dict`, a small set of attribute names are
**reserved** for the dict / Config API and cannot be used as config keys
without surprising behavior:

```text
items, keys, values, get, update, pop, clear, copy, setdefault, as_dict, app,
provenance, provenance_history, provenance_dump
```

If your configuration legitimately needs a key named (say) `items` or `keys`,
use bracket-style access only:

```python
cfg = Config({"items": [1, 2, 3]})
cfg["items"]   # ✓ works as expected — returns [1, 2, 3]
cfg.items      # ✗ returns the bound method <dict.items of {...}>, NOT [1, 2, 3]
```

In practice, prefer renaming such keys at the source (e.g. `record_items`,
`event_keys`). The dot-notation accessor (`cfg.foo.bar`) is unaffected for
any key that is not in the reserved list above.

### Multi-App Configuration (v0.4.0)

confy v0.4.0 supports configuring multiple applications from a single config file.
This is designed for ecosystems where several packages share one configuration
(e.g., llmcore + semantiscan).

```python
from confy.loader import Config

# Register per-app defaults and env var prefixes
cfg = Config(
    app_defaults={
        "myapp": {"debug": False, "port": 8080},
        "worker": {"threads": 4, "timeout": 30},
    },
    file_path="config.toml",      # Single file with [myapp] and [worker] sections
    prefix="GLOBAL",              # GLOBAL_* env vars (primary prefix)
    app_prefixes={
        "myapp": "MYAPP",         # MYAPP_* env vars → cfg.myapp.*
        "worker": "WORKER",       # WORKER_* env vars → cfg.worker.*
    },
)

# Access via app() accessor or direct attribute
cfg.app("myapp").port       # → 8080 (or file/env override)
cfg.worker.threads          # → 4 (same thing, just different syntax)
cfg.app("unknown")          # → Config({}) — empty, no error
```

The TOML file would look like:

```toml
[myapp]
debug = true
port = 9090

[worker]
threads = 8

[logging]
level = "DEBUG"    # Shared section, not app-specific
```

### Provenance Tracking (v0.4.0)

Enable with `track_provenance=True` to trace where each config value came from:

```python
cfg = Config(
    defaults={"db": {"port": 5432}},
    file_path="config.toml",       # Contains [db] port = 3306
    track_provenance=True,
)

# See where the current value came from
p = cfg.provenance("db.port")
print(p)  # db.port = 3306  ← file:config.toml

# See the full override chain
for entry in cfg.provenance_history("db.port"):
    print(f"  {entry.source}: {entry.value}")
# Output:
#   defaults: 5432
#   file:config.toml: 3306

# Dump all provenance
cfg.provenance_dump()  # {"db.port": "file:config.toml", ...}
```

### Argparse integration

`confy` includes an optional helper function to simplify integration with Python's built-in `argparse` module.

Located in `confy/argparse_integration.py`.

```python
# your_script_using_argparse.py
import argparse
from confy.loader import Config
from confy.argparse_integration import load_config_from_args
from confy.exceptions import MissingMandatoryConfig

# 1. Define your application's specific defaults and mandatory keys
app_defaults = {"server": {"port": 8080, "workers": 4}, "logging": {"level": "INFO"}}
app_mandatory = ["server.port"] # Ensure the server port is always configured

# 2. Create your main argument parser (as usual)
parser = argparse.ArgumentParser(description="My Awesome Application")
parser.add_argument("--workers", type=int, help="Override number of worker processes.")
parser.add_argument("--enable-feature-x", action="store_true", help="Enable experimental feature X.")
# Add other application-specific arguments...

# 3. Use load_config_from_args to handle confy's arguments and initialize Config
#    It parses only --config, --prefix, and --overrides, leaving others for your parser.
try:
    # Pass your app's defaults and mandatory keys here.
    # load_config_from_args builds an intermediate overrides_dict from the --overrides arg.
    cfg = load_config_from_args(defaults=app_defaults,
                                mandatory=app_mandatory)

    # 4. Parse the *remaining* command-line arguments using your parser.
    # args will contain only your application-specific arguments (--workers, --enable-feature-x).
    args = parser.parse_args()

    # 5. Optionally, merge argparse results into confy as final overrides
    # This gives command-line flags the absolute highest priority.
    argparse_overrides = {}
    if args.workers is not None:
        argparse_overrides["server.workers"] = args.workers
    if args.enable_feature_x:
        argparse_overrides["features.feature_x_enabled"] = True
    # Add other args as needed...

    # Re-initialize or update config if necessary, or handle directly
    # For simplicity, let's assume we use the values directly or update cfg manually if needed.
    # Example: Update the worker count if provided via CLI arg
    if "server.workers" in argparse_overrides:
        cfg.server.workers = argparse_overrides["server.workers"] # Direct update


    print(f"Starting server on port {cfg.server.port} with {cfg.server.workers} workers.")
    if cfg.get("features.feature_x_enabled"): # Check if feature X was enabled
         print("Feature X is ENABLED.")
    print(f"Logging level set to: {cfg.logging.level}")


except MissingMandatoryConfig as e:
    print(f"Configuration error: Missing required keys: {e.missing_keys}")
    # parser.print_help() # Optionally show help on config error
    exit(1)
except Exception as e:
    print(f"An error occurred: {e}")
    exit(1)

# Continue with application logic using the 'cfg' object...
# print(f"Final effective configuration: {cfg.as_dict()}")

```

The `load_config_from_args` function:

1.  Creates a temporary `argparse.ArgumentParser`.
2.  Adds arguments: `--config`, `--prefix`, `--overrides`.
3.  Uses `parse_known_args()` to extract values for *only* these three arguments, leaving others untouched.
4.  Parses the `--overrides` string (comma-separated `dot.key:json_value`) into a dictionary.
5.  Initializes and returns a `Config` instance using the extracted `config` path, `prefix`, the parsed `overrides` dictionary, and the `defaults` and `mandatory` lists you provided.

This allows your main script to handle its own arguments cleanly after `confy` has loaded the base configuration.

-----

## CLI Usage

The `confy` command-line tool provides convenient ways to interact with configuration files without writing Python code. It's built using the **Click** library.

### Global options

These options are processed *before* any subcommand runs. They define how the initial configuration state is loaded for the subcommand to operate on.

```bash
Usage: confy [OPTIONS] COMMAND [ARGS]...

  confy CLI: inspect & mutate JSON/TOML configs via dot-notation.

  Supports defaults, config files (JSON/TOML), .env files, environment
  variables (with prefix), and explicit overrides. Requires Python 3.10+.

Options:
  -c, --config PATH        Path to the primary JSON or TOML config file to load.
  -p, --prefix TEXT        Case-insensitive prefix for environment variable
                           overrides (e.g., 'APP_CONF').
  --overrides TEXT         Comma-separated 'dot.key:json_value' pairs for final
                           overrides (e.g., "db.port:5433,log.level:\"DEBUG\"").
                           Note: legacy syntax — comma-splits the input first,
                           so JSON arrays/objects containing commas are
                           corrupted. Use --overrides-json for those cases.
  --overrides-json TEXT    JSON object string with overrides; supports
                           compound values (arrays/objects) without
                           comma-corruption. Keys may use dot-notation.
                           Applied AFTER --overrides (last wins on conflict).
                           Example:
                             --overrides-json '{"db":{"hosts":["h1","h2"]}}'
  --defaults PATH          Path to a JSON file containing default values
                           (lowest precedence). Supports ~ and $VAR expansion
                           (I-02). Must contain a JSON object at the top level;
                           non-object payloads (array/string/number/bool) are
                           rejected with a friendly error (I-03).
  --mandatory TEXT         Comma-separated list of mandatory dot-keys that
                           must exist after loading.
  --dotenv-path PATH       Explicit path to the .env file to load. If not set,
                           searches automatically.
  --no-dotenv              Disable automatic loading of the .env file.
  --track-provenance       Enable provenance tracking (records where each
                           config value came from). Disabled by default.
  -h, --help               Show this message and exit.
```

> **Reminder:** The loading precedence (`defaults` → `config file` → `.env` → `environment variables` → `overrides` → `overrides-json`) applies fully when using the CLI tool.

#### `--overrides` vs `--overrides-json` (v0.4.1, I-04)

The legacy `--overrides` flag uses a simple comma-split parser:

```bash
confy --overrides 'db.host:"primary",db.port:5433' dump
```

This works for scalar values but breaks on JSON arrays/objects because the
comma inside the value collides with the pair separator:

```bash
# ❌ broken: comma-shredded into 3 fragments
confy --overrides 'arr:[1, 2, 3]' dump

# ✅ correct: --overrides-json parses the whole payload as JSON
confy --overrides-json '{"arr": [1, 2, 3]}' dump
```

When both are supplied for the same dot-path, `--overrides-json` wins
(it is applied *after* `--overrides`):

```bash
confy --overrides 'k:"from_classic"' --overrides-json '{"k": "from_json"}' dump
# → {"k": "from_json"}
```

### Subcommands

Subcommands operate on the configuration state loaded via the global options.

| Command   | Description                                                         | Arguments/Options                                     | Notes                                                                 |
| :-------- | :------------------------------------------------------------------ | :---------------------------------------------------- | :-------------------------------------------------------------------- |
| `get`     | Print the final value of a specific key (dot-notation) as JSON.     | `KEY`                                                 | Exits with error if key not found.                                    |
| `set`     | Update a key **in the source config file** specified by `-c`.       | `KEY VALUE` (VALUE is parsed as JSON if possible)     | **Modifies file on disk.** Requires `-c`. Preserves original format (JSON/TOML using `tomli-w`). |
| `exists`  | Check if a key exists in the final merged config.                   | `KEY`                                                 | Exits with status 0 if key exists, 1 otherwise. Prints `true`/`false`. |
| `search`  | Find keys/values matching patterns (plain text, glob `*?`, regex).  | `[--key PAT] [--val PAT] [-i]` (ignore case)          | Requires `--key` or `--val`. Outputs matching subset as JSON.         |
| `dump`    | Pretty-print the entire final merged config as JSON to stdout.      |                                                       | Useful for debugging the final state.                                 |
| `convert` | Convert the final merged config to JSON or TOML format.             | `--to {json|toml}` `--out FILE` (optional output file) | Uses `tomli-w` for TOML output.                                       |

#### `get` Example

Retrieve and print a specific value from the final merged configuration.

```bash
# Get the database host after considering defaults, config.toml, env vars, etc.
confy -c config.toml -p MYAPP get database.host
# Output might be: "prod.db.example.com" (JSON string)

# Get a potentially overridden boolean flag
confy -c config.toml --overrides "feature_flags.new_dashboard:true" get feature_flags.new_dashboard
# Output: true (JSON boolean)
```

#### `set` Example

Modify a value **directly in the file specified by `-c`**. This command *reads* the file, *updates* the value in memory, and then *writes* the entire structure back, preserving the original format.

```bash
# Change the database port number in config.toml
confy -c config.toml set database.port 5435
# Output: Set database.port = 5435 in config.toml

# Set a nested string value in config.json (note JSON string quoting)
confy -c config.json set logging.format '"%(asctime)s - %(levelname)s - %(message)s"'
# Output: Set logging.format = '%(asctime)s - %(levelname)s - %(message)s' in config.json

# Set a boolean value in config.toml
confy -c config.toml set feature_flags.new_dashboard false
# Output: Set feature_flags.new_dashboard = False in config.toml
```

> **Caution:** The `set` command performs an **in-place modification** of the specified configuration file. Always ensure you have backups or use version control. It requires the `-c` option to know which file to modify.

#### `exists` Example

Check if a key is present in the *final* configuration after all sources have been merged. Useful for scripts.

```bash
# Check if the database host is configured
confy -c config.toml exists database.host && echo "Host is configured."
# Output:
# true
# Host is configured.
# Exit code: 0

# Check for a key that likely doesn't exist
confy -c config.toml exists non_existent_section.key || echo "Key not found."
# Output:
# false
# Key not found.
# Exit code: 1
```

#### `search` Example

Find keys or values using patterns. The default auto-detection picks between
plain text, glob (`*?[]`), and regex based on the pattern shape. For explicit
control, use the **mutually-exclusive mode flags** added in v0.4.1 (I-08):

| Flag      | Force mode | Notes                                                                                                      |
| --------- | ---------- | ---------------------------------------------------------------------------------------------------------- |
| (none)    | auto       | Heuristic detection; glob is **always case-insensitive** in this mode regardless of `-i` (preserved for back-compat, I-09). |
| `--regex` | regex      | `re.search` semantics. Invalid regex syntax returns no matches (vs. silent substring degradation in auto). |
| `--glob`  | glob       | `fnmatch` semantics. **Case-sensitive by default**; combine with `-i` to fold case (I-09 resolution).      |
| `--exact` | exact      | String equality. **Case-sensitive by default**; combine with `-i` to fold case.                            |

```bash
# Auto mode (legacy behavior)
confy -c config.toml search --key 'database.*'
confy -c config.toml search --key '*port' -i
confy -c config.toml search --val 'localhost'
confy -c config.toml search --val '^(true|false)$' -i
confy -c config.toml search --key 'db.*' --val '*prod*' -i

# Force regex even on a plain word (substring search):
confy -c config.toml search --key host --regex

# Force exact-literal matching of a regex-looking string:
confy -c config.toml search --key 'feature.flags' --exact

# Force case-sensitive glob (auto mode would lowercase both sides):
confy -c config.toml search --key 'DB*' --glob
```

#### `dump` Example

Display the entire resolved configuration as a JSON object, reflecting all merged sources.

```bash
# Show the final configuration after loading multiple sources
confy \
  --defaults defaults.json \
  -c config.toml \
  -p MYAPP \
  --overrides "logging.level:\"DEBUG\",network.timeout:60" \
  dump
# Output: A JSON representation of the final merged configuration.
```

#### `convert` Example

Output the final merged configuration in either JSON or TOML format.

```bash
# Convert the effective configuration derived from config.toml (and others) to JSON on stdout
confy -c config.toml -p MYAPP convert --to json

# Convert the effective configuration to TOML and save it to a new file
confy -c config.json --defaults def.json convert --to toml --out effective_config.toml
# Output: Wrote TOML output to effective_config.toml
```

-----

## Advanced Usage

### Environment Overrides Explained

  - When a `prefix` is provided (e.g., `MYAPP`), `confy` scans environment variables starting with that prefix (case-insensitive).
  - The prefix itself is removed, and the rest of the variable name is converted to `lowercase`.
  - **Underscore Mapping:**
      - Double underscores (`__`) are converted to a single underscore (`_`) in the resulting key part.
      - Single underscores (`_`) are converted to dots (`.`).
      - This allows environment variables to target configuration keys containing underscores.
      - **Examples:**
          - `MYAPP_DATABASE_HOST` → `database.host`
          - `MYAPP_LOGGING_LEVEL` → `logging.level`
          - `MYAPP_FEATURE_FLAGS__BETA_FEATURE` → `feature_flags.beta_feature` (explicit `__` form; the `feature_flags` section need not exist)
          - `MYAPP_USER__LOGIN_ATTEMPTS` → `user.login_attempts` (explicit `__` form)
          - `MYAPP_RAW_KEY_WITH__UNDERSCORE` → `raw_key_with_underscore` (if no matching section found during remapping)
  - **Remapping (Heuristic 0, v0.4.1):** After the initial underscore conversion, `confy` attempts to remap the resulting dot-key (e.g., `feature.flags.beta.feature`) to match the structure of your `defaults` and config file data (e.g., to `feature_flags.beta_feature`). The remapper iterates over **every** underscore-prefix position in the reconstructed flat key (`feature_flags_beta_feature`), from longest to shortest, and uses the first prefix that resolves to a dict in your base config. So `MYAPP_FEATURE_FLAGS_BETA_FEATURE` (without `__`) correctly nests under `feature_flags.beta_feature` if `feature_flags` is a known section — even though there are four single-underscore segments. See `_remap_and_flatten_env_data` in `loader.py` for the full algorithm (I-01 fix).
  - **Fallback for unresolvable keys (`env_remap_fallback`, v0.4.1, I-05):** If no remap target is found, `confy` falls back to one of two shapes. The strategy is controlled by the `env_remap_fallback` constructor parameter:
      - `"auto"` (default) — historical behavior: nested (dot-form) when `load_dotenv_file=True` or `prefix=""`, flat (underscore-form) otherwise.
      - `"nested"` — always preserve dot-form (e.g. `env.only`).
      - `"flat"` — always collapse to underscore-form (e.g. `env_only`).

    The `argparse_integration.load_config_from_args` helper passes `env_remap_fallback="flat"` for deterministic behavior independent of the `.env` loading toggle.
  - **Type Parsing:** `confy` attempts to parse the environment variable's value as JSON. This allows setting booleans (`true`/`false`), numbers (`123`), and properly quoted strings (`"hello world"`). If JSON parsing fails, the raw string value is used.
    ```bash
    export MYAPP_DATABASE_PORT=5433         # Parsed as integer 5433
    export MYAPP_FEATURE_FLAGS_ENABLED=true # Parsed as boolean True
    export MYAPP_LOGGING_LEVEL='"DEBUG"'    # Parsed as string "DEBUG"
    export MYAPP_API_KEY=raw_secret_key     # Used as raw string "raw_secret_key"
    ```
  - **Special tokens NOT parsed as float (v0.4.1, I-06):** The IEEE 754 special tokens `inf`, `-inf`, `+inf`, `infinity`, `nan`, `-nan`, `+nan` (case-insensitive) are intentionally **rejected** by the value parser and round-tripped as raw strings. End-user configuration values rarely mean the literal special float; `MYAPP_TIMEOUT=inf` almost always means the three-character string. If you genuinely need positive infinity, set the value programmatically via `overrides_dict={"timeout": math.inf}`.

### `.env` File Handling Details

  - **Automatic Loading**: Enabled by default (`load_dotenv_file=True`). `confy` uses `dotenv.load_dotenv(override=False)` which searches the current directory and parent directories for a `.env` file.
  - **No Override**: Crucially, `load_dotenv` with `override=False` **will not** change the value of an environment variable that is *already set* in the environment *before* `load_dotenv` is called. This means explicit environment variables set outside the script take precedence over `.env` file values.
  - **Disabling**: Pass `load_dotenv_file=False` to the `Config` constructor or use the `--no-dotenv` flag in the CLI.
  - **Custom Path**: Specify an exact path using `dotenv_path='/path/to/your/.env'` or the `--dotenv-path` CLI flag. This disables the automatic directory search.
  - **Interaction with Prefix**: Variables loaded from `.env` are simply added to `os.environ`. They are then subject to the same `prefix` filtering and underscore mapping as any other environment variable during the environment variable loading step. Ensure your `.env` variables include the necessary prefix and use double underscores (`__`) if needed (e.g., `MYAPP_FEATURE_FLAGS__BETA_FEATURE=true` in `.env` if your prefix is `MYAPP`).

### Chaining Multiple Sources

Leverage the precedence order by combining sources strategically.

```bash
# Example script execution:
# Use system-wide defaults, override with a user config,
# further override with env vars for production,
# and finally apply specific command-line overrides.

confy \
  --defaults /etc/myapp/defaults.json \
  -c ~/.config/myapp/user_config.toml \
  -p MYAPP_PROD \
  --overrides "logging.level:\"TRACE\",database.timeout:120" \
  dump
```

### Error Handling Strategies

Robust applications should anticipate configuration errors:

  - **Missing Mandatory Keys (`MissingMandatoryConfig`)**: Catch this exception specifically. Log the `e.missing_keys` list and provide helpful instructions to the user on how to set these required values (e.g., "Please set DATABASE\_HOST in your config file or MYAPP\_DATABASE\_HOST environment variable"). Exit gracefully.
  - **File Not Found (`FileNotFoundError`)**: Decide if a missing config file (`-c` or `--defaults`) is acceptable. If defaults/env vars are sufficient, log a warning. If the file is essential, log an error and exit.
  - **Parsing Errors (`RuntimeError` wrapping `JSONDecodeError`/`TOMLDecodeError`)**: Indicates a syntax error in a JSON or TOML file. Log the specific error and filename, instruct the user to validate the file syntax, and exit.
  - **General Exceptions**: Catch `Exception` as a last resort for unexpected issues during loading. Log the error details and exit.

<!-- end list -->

```python
# Example error handling block from Quickstart, expanded
try:
    cfg = Config(...) # Your Config initialization
except MissingMandatoryConfig as e:
    logging.error(f"Missing mandatory configuration keys: {', '.join(e.missing_keys)}")
    print(f"ERROR: Please define the following required settings: {', '.join(e.missing_keys)}")
    # Add hints on where to define them (e.g., config file, .env, env vars)
    exit(1)
except FileNotFoundError as e:
    logging.error(f"Configuration file not found: {e.filename}")
    print(f"ERROR: Configuration file not found at {e.filename}")
    exit(1)
except RuntimeError as e: # Catches parsing errors
     logging.error(f"Failed to parse configuration file: {e}")
     print(f"ERROR: Could not parse configuration file. Please check syntax. Details: {e}")
     exit(1)
except Exception as e:
    logging.exception("An unexpected error occurred during configuration setup.")
    print(f"FATAL: An unexpected error occurred: {e}")
    exit(1)
```

-----

## Upcoming features

  - **`diff`**: Compare two configurations (from files or loaded states) and highlight added, removed, or changed keys/values.
  - **`validate`**: Check the loaded configuration against a predefined schema (e.g., JSON Schema) or a set of custom validation rules (e.g., check if ports are within a valid range).
  - **`env`**: Export the current final configuration state as a series of shell `export KEY=VALUE` statements, suitable for sourcing in scripts.
  - **`repl`**: Start an interactive Read-Eval-Print Loop for browsing and interactively modifying the configuration state.
  - **`encrypt`/`decrypt`**: Integrate with a secrets management system or library (like `cryptography`) to handle encrypted values within the configuration files. Could involve specific key naming conventions (e.g., `db.password_encrypted`).
  - **`template`**: Render configuration files using a templating engine like Jinja2, allowing dynamic values based on environment or other variables before loading.

-----

## Testing

`confy` ships with a comprehensive test suite layered by purpose: pure-function unit tests, multi-component integration tests, CLI tests via Click's `CliRunner`, and robustness tests for edge cases and missing optional dependencies. Total coverage sits at **~95.8%** (loader 98.3%, CLI 87.6%, argparse helper 100%).

### Quick run

Install dev dependencies and run the full suite:

```bash
pip install -e ".[dev]"
pytest                                  # 733 passed, 4 xfailed in ~1.6 s
pytest --cov=confy --cov-report=term-missing
```

### Running a specific layer

Each test layer is tagged with a [pytest marker](https://docs.pytest.org/en/stable/example/markers.html), declared in `pyproject.toml`:

```bash
pytest -m unit                          # pure-function unit tests (fastest)
pytest -m integration                   # multi-component, file + env
pytest -m cli                           # click CLI via CliRunner
pytest -m robustness                    # malformed input + optional deps
```

Marker selection composes: `pytest -m "unit or robustness"`.

### Suite layout

```
tests/
├── conftest.py                         # autouse env + cwd snapshot fixtures
├── test_loader.py                      # legacy monolithic tests (4 xfail)
├── v040/                               # v0.4.0 phase tests
├── unit/                               # pure-function tests (P2 + P3)
│   ├── test_parse_value.py
│   ├── test_dot_path.py
│   ├── test_deep_merge.py
│   ├── test_utils.py
│   ├── test_env_collect.py
│   ├── test_env_remap.py
│   ├── test_config_init_sources.py
│   └── test_config_access.py
├── integration/                        # end-to-end Config (P4)
│   ├── test_precedence_matrix.py
│   ├── test_dotenv_integration.py
│   ├── test_multifile.py
│   ├── test_app_namespaces.py
│   ├── test_mandatory_validation.py
│   └── test_round_trip.py
├── cli/                                # Click CLI surface (P5)
│   ├── conftest.py                     # CliRunner + config-file factories
│   ├── test_cli_root.py
│   ├── test_cli_get.py
│   ├── test_cli_set.py
│   ├── test_cli_exists.py
│   ├── test_cli_dump.py
│   ├── test_cli_search.py
│   ├── test_cli_convert.py
│   ├── test_cli_provenance.py
│   ├── test_cli_overrides_parsing.py
│   └── test_cli_defaults_loading.py
├── argparse_integration/               # argparse helper (P6)
│   └── test_argparse_integration.py
└── robustness/                         # P6: defensive + edge
    ├── test_optional_deps.py
    ├── test_loader_branches.py
    └── test_edge_cases.py
```

### Coverage gate

`pyproject.toml` enforces a minimum of `fail_under = 90`. Drop below that and `pytest --cov=confy` exits with code 1. The actual achieved coverage (~98.3% after the v0.4.1 fixes) is well above the gate; the margin exists so a small, conscious regression doesn't immediately break CI while still catching unintended drops.

### Previously xfailed tests (now passing, v0.4.1)

Prior to v0.4.1, four tests in `tests/test_loader.py` were marked
`@pytest.mark.xfail(strict=True)` because they depended on a multi-underscore
remapping behavior (`feature_flags.beta_feature` from
`MYAPP_FEATURE_FLAGS_BETA_FEATURE` without explicit `__`) that the original
Heuristic 0 did not implement. The I-01 fix in v0.4.1 (longest-underscore-prefix
scan in `_remap_and_flatten_env_data`) makes all four tests pass; the
`xfail` markers have been removed. See `tests/unit/test_env_remap.py` →
`TestHeuristic0LongestPrefix` for the unit-level pins of the fix.

### Adding new tests

See [CONTRIBUTING.md](CONTRIBUTING.md) for the test-organization conventions, available fixtures, and which marker to use for new tests.

-----

## Contributing

Contributions, bug reports, and feature requests are welcome. See **[CONTRIBUTING.md](CONTRIBUTING.md)** for the full guide, which covers:

* Development setup and dev-dependency installation.
* The test-suite organization (the unit / integration / cli / robustness layers).
* Where to put new tests and which marker to use.
* The autouse fixtures and what they protect against.
* The full list of known library quirks (xfailed tests, parser edge cases, undocumented behaviors).
* PR workflow and commit-message conventions.

In short:

1. Fork → branch from `main` (e.g., `feat/short-description`).
2. Write code AND tests.
3. Run `pytest` locally; ensure the coverage gate (`fail_under=90`) holds.
4. Update `README.md` or docstrings if the change affects usage.
5. Open a PR against `main` with a clear summary of motivation and scope.

Please adhere to PEP 8 and the existing code style. The project uses `basedpyright` for type checking and `ruff` for linting; running those locally before submitting is recommended.

-----

## License

This project is licensed under the **MIT License**. See the `LICENSE` file in the repository for the full text.
