# confy - integration and usage

**confy** is a minimal, flexible Python configuration library (with an accompanying CLI tool) for managing application settings. It provides a unified way to handle configuration from multiple sources and access it conveniently in code. Key features include:

- **Multiple Config Sources:** Load configuration from **JSON** and **TOML** files, environment-specific **`.env`** files, system **environment variables**, and in-code overrides via Python dictionaries.
- **Dot-Notation Access:** Access configuration values as attributes (e.g. `cfg.database.host`), with nested dictionaries auto-converted to support chained dot notation.
- **Default Values and Mandatory Keys:** Define default settings to ensure every config key has a fallback, and mark essential keys as **mandatory** to enforce their presence (raises an error if missing).
- **Environment Variable Overrides:** Override any configuration using environment variables, with support for an optional **prefix** (e.g. `MYAPP_DATABASE_PORT=5432`) to scope your app’s vars. Confy maps these env vars to config keys (underscores and double-underscores are handled for nested keys – see details below).
- **Final Overrides via Dictionary:** Apply a final layer of overrides by passing a Python **dictionary** of config keys to values. This is ideal for integrating with CLI argument parsers (like `argparse` or `click`) where parsed options can override config settings.
- **CLI Tool for Config Files:** Use the built-in `confy` CLI to directly inspect configuration (`get`, `dump`, `search`, `exists`) or modify files (`set`, `convert`) via dot-notation keys.

Throughout this guide, we’ll walk through setting up and using confy in a project, covering installation, configuration sources, examples of usage in scripts and CLI applications, and best practices to avoid common pitfalls.

## Installation

Make sure you have **Python 3.10+** installed, as confy requires it. Install confy from PyPI using pip:

```bash
pip install confy
```

This will install both the confy library (for use in Python via `import confy`) and the `confy` command-line tool. Alternatively, you can install from source by cloning the GitHub repository and running `pip install .` in the project directory.

## Configuration Sources and Precedence

Confy merges multiple configuration sources in a specific layered order, where later sources override earlier ones on a key-by-key basis:

1. **Defaults:** The base configuration given by `defaults` (a dict) when initializing confy. These are the lowest precedence (used only if not overridden by any other source).
2. **Config File:** Settings loaded from a JSON or TOML file (if provided via `file_path`). File values override defaults if the same keys exist.
3. **`.env` File:** If present, a `.env` file is automatically loaded (by default) using `python-dotenv`. The variables from `.env` are put into the environment. They override earlier sources (defaults & file) when mapped to config keys, but **do not override** any environment variables that were already set in the system before loading the file.
4. **Environment Variables:** Actual OS environment variables (optionally filtered by a prefix) override all of the above. They will take precedence over values from the `.env` file if the names conflict.
5. **Overrides Dictionary:** Any final overrides passed in via a Python dictionary (e.g. from command-line args) have the highest precedence and will override all other sources for those keys.

This predictable precedence order – *defaults → file → .env → env vars → overrides* – ensures you can layer configuration (for example, providing defaults, then letting a config file or environment-specific variables override them, and finally using command-line flags to override everything for quick changes).

## Setting Up Default Configuration Values

It’s good practice to start by defining a dictionary of **default configuration values** for your application. These defaults act as the baseline config that will be used if no other source provides a particular setting. You can also specify which keys are **mandatory** (required) to prevent running with missing critical configs.

For example, here’s a default config dict defining some settings and a list of mandatory keys:

```python
# Define default settings for the application:
defaults = {
    "database": {"host": "localhost", "port": 5432, "user": "guest"},
    "logging":  {"level": "INFO", "format": "default"},
    "feature_flags": {"new_dashboard": False}
}

# Define mandatory keys (using dot-notation even for nested keys):
mandatory_keys = [
    "database.host",
    "database.port",
    "database.user",
    "logging.level"
]
```

In the above, `defaults` provides a sane baseline (e.g. a local database and default logging config). The `mandatory_keys` list specifies keys that **must** have values after loading all sources – if any of these are still missing, confy will raise a `MissingMandatoryConfig` exception to alert you. Using defaults ensures your app can run with reasonable settings out-of-the-box, while mandatory keys ensure you don’t accidentally run without essential configuration (like database connection info).

When you initialize confy’s `Config`, you will pass these in (via `defaults=...` and `mandatory=...`), as shown later.

## Loading Configuration from JSON or TOML Files

Confy can load configuration from an external file, supporting both JSON and TOML formats. To use this, provide the file path when creating the `Config` object (e.g. `Config(file_path="config.toml", ...)`). Under the hood, confy uses modern TOML libraries (`tomli` for reading and `tomli-w` for writing) for full TOML v1.0.0 support, and Python’s built-in JSON for `.json` files.

**Example configuration file (TOML):**

```toml
# config.toml - Example configuration file

[database]
host = "prod.db.example.com"  # Overrides default host
user = "prod_user"            # Overrides default user
# Port is not specified here; default (5432) will be used unless overridden elsewhere

[logging]
level = "WARNING"             # Overrides default "INFO" (can be overridden by env/CLI)

[feature_flags]
new_dashboard = false         # Overrides default, but can be overridden by CLI or env
```



In this `config.toml`, values specified will override the defaults we defined earlier. For instance, the database `host` and `user` here replace the default `"localhost"` and `"guest"`. The `port` is not set in the file, so it will fall back to the default (`5432`) unless an environment variable or override provides it. The logging level is set to `"WARNING"` in the file, which would override the default `"INFO"` (but as the comment notes, it could still be overridden later by an environment variable or CLI override).

To load a config file, simply pass its path to `Config`:

```python
from confy.loader import Config
cfg = Config(file_path="config.toml", defaults=defaults, mandatory=mandatory_keys)
```

In this example, confy will read `config.toml` and merge it on top of the `defaults`. If the file doesn’t exist or contains invalid syntax, a `FileNotFoundError` or parsing error will be raised (more on error handling later). By default, confy will also look for a `.env` file after loading this file, and then apply env vars and overrides as described in the precedence list.

## Environment Variable Overrides (and `.env` Support)

Confy allows environment variables to override configuration values, which is very useful for adjusting settings per environment (e.g. dev, staging, production) and for keeping secrets out of config files.

**Prefix:** To avoid picking up unrelated environment variables, you can specify a prefix when initializing `Config` (e.g. `prefix="MYAPP"`). If a prefix is set, confy will only consider environment variables that start with that prefix (case-insensitive) and then map them into your config structure. For example, with `prefix="MYAPP"`, an env var `MYAPP_DATABASE_HOST` would map to `cfg.database.host`. If no prefix is specified (`prefix=None` or empty), confy will consider all environment variables as potential overrides (which can be convenient for small apps, but usually a prefix is recommended to avoid conflicts).

**Mapping Rules:** Confy transforms environment variable names to config keys as follows:

- The prefix (e.g. `MYAPP_`) is removed, and the remaining name is lowercased.
- Single underscores (`_`) in the env var name become **dots** in the config key, indicating nesting.
- Double underscores (`__`) become a single underscore `_` in the key. This allows representing keys that themselves contain underscores or to separate words in a single key part.
- After these conversions, confy tries to **remap** the key to match your config structure. For example, `MYAPP_FEATURE_FLAGS__BETA_FEATURE` -> `feature_flags.beta_feature` (because `feature_flags` is a section in our defaults). Similarly, `MYAPP_DATABASE_HOST` -> `database.host`, and `MYAPP_USER__LOGIN_ATTEMPTS` -> `user.login_attempts`.

**Type Conversion:** The values of environment variables are strings, but confy will attempt to parse them as JSON to preserve type information. This means if you export an env var as `MYAPP_FEATURE_FLAGS_ENABLED=true`, confy will interpret it as a boolean `True` (not the string `"true"`), and `"123"` would become an integer 123. If the value isn’t valid JSON, it remains a string. For example:

```bash
export MYAPP_DEBUG_MODE=true      # becomes boolean True
export MYAPP_MAX_CONNECTIONS=100  # becomes integer 100
export MYAPP_WELCOME_MSG='"Hello"' # becomes string "Hello" (note the quotes to force string)
export MYAPP_VERSION_TAG=v1.2.3   # "v1.2.3" is not JSON, so it stays as the string "v1.2.3"
```

**Automatic `.env` Loading:** By default, confy will look for a file named `.env` in the current directory or its parents and load it (using `python-dotenv`) when you create a `Config`. This is handy for development: you can put environment variable definitions in a local `.env` file, and confy will load them into the environment as if they were set in the OS. *Important:* The `.env` loading is non-destructive – it **will not override** any environment variables that are already set in the environment before your program runs. In other words, real environment variables take priority over the `.env` file values. You can turn off automatic `.env` loading by passing `load_dotenv_file=False` to `Config`, or specify a custom path via `dotenv_path="path/to/your.env"` if your env file has a different name or location.

**Example `.env` file:**

```bash
# .env file - example environment definitions

# All keys here use the 'MYAPP_' prefix as configured, so confy will pick them up:
MYAPP_DATABASE_USER=env_db_user              # Overrides the database.user from file/default
MYAPP_SECRETS_API_KEY="dotenv_abc123xyz"     # Supplies a new key (secrets.api_key) from .env

# This will NOT override an existing env var MYAPP_LOGGING_LEVEL (if one was already set externally)
MYAPP_LOGGING_LEVEL=INFO

# Using double underscore to map to a nested key with an underscore
MYAPP_FEATURE_FLAGS__BETA_FEATURE=true       # Becomes feature_flags.beta_feature in config

# Variables without the prefix are ignored by confy (they'll load into os.environ, but confy only 
# looks at those starting with MYAPP_ prefix in this example).
OTHER_ENV_VAR=some_other_value
```



In this example, if `prefix="MYAPP"`, confy will:

- Set `cfg.database.user` to `"env_db_user"` (overriding any default or file value) from `MYAPP_DATABASE_USER`.
- Add a new key `cfg.secrets.api_key` with value `"dotenv_abc123xyz"` (since our code could access it via `cfg.secrets.api_key`).
- For `MYAPP_LOGGING_LEVEL=INFO`: if no environment variable `MYAPP_LOGGING_LEVEL` was already set externally, it will be loaded and override the logging level (in this case to "INFO"). But if `MYAPP_LOGGING_LEVEL` was already set in the environment (e.g., by the OS or shell), the `.env` file’s value is ignored.
- `MYAPP_FEATURE_FLAGS__BETA_FEATURE=true` will set `cfg.feature_flags.beta_feature = True` (notice the double underscore in the env var name becoming an underscore in the key).
- `OTHER_ENV_VAR` is not prefixed with `MYAPP_`, so confy will ignore it when mapping to config (it remains in `os.environ` but doesn't affect `cfg` since a prefix is in use).

When initializing confy, you pass the prefix string if you want this behavior:

```python
cfg = Config(
    file_path="config.toml",
    defaults=defaults,
    prefix="MYAPP",           # Only consider env vars starting with MYAPP_
    load_dotenv_file=True,    # (Default) load .env automatically
    # dotenv_path="custom.env",  # Could specify a custom .env file path if needed
    overrides_dict=cli_overrides,
    mandatory=mandatory_keys
)
```

*(In this snippet, assume `cli_overrides` is a dictionary of override values and `mandatory_keys` is the list of mandatory keys as defined earlier.)*

By including `prefix="MYAPP"`, only env vars with that prefix will apply (making it easier to run multiple apps on the same machine without env conflicts). And because `load_dotenv_file` is true by default, confy would load `.env` automatically; if you wanted to skip loading a `.env`, you could set `load_dotenv_file=False` or use the `--no-dotenv` flag in the CLI.

## Overrides via Dictionary (CLI Argument Overrides)

After defaults, file, and environment variables, the final layer of configuration is an **overrides dictionary**. This allows your application to programmatically override configuration values – typically using command-line arguments. For example, if a user passes `--port 5433` to your script, you might want that to override whatever port was in the config file or defaults.

Confy’s `Config` accepts a `overrides_dict` parameter, which should be a mapping of config keys to desired values. These keys can be specified in **dot-notation strings** to target nested config values. For instance:

```python
# Example: overrides from command-line arguments
cli_overrides = {
    "database.port": 5433,      # override the database.port (e.g., use 5433 instead of default/file)
    "logging.level": "DEBUG",   # override logging.level (e.g., set DEBUG logging)
    "feature_flags.new_dashboard": True  # override to enable the new_dashboard feature
}
```



In this dictionary, the keys are strings indicating the config path, and the values are the new settings (with correct type – int, str, bool, etc.). When we pass `cli_overrides` to `Config(overrides_dict=...)`, those values will **take precedence over all other sources** for the specified keys. For example, `"database.port": 5433` ensures `cfg.database.port` will end up as 5433 regardless of what was in defaults, the config file, or environment variables for that key.

Just like with environment variables, confy will attempt to parse any string values in the overrides dict as JSON to infer types. In the above `cli_overrides`, we already used an integer and boolean in Python, so their types are clear. But if you were constructing this dict from raw strings (e.g., parsing a manual `--overrides` argument), confy would interpret `"True"` or `"false"` as booleans, numbers as ints/floats, etc., when possible.

### Combining All Sources in Code

Bringing it all together, a typical confy initialization in a script might look like this:

```python
from confy.loader import Config

cfg = Config(
    file_path="config.toml",    # Load this JSON/TOML file (if None, skip file layer)
    prefix="MYAPP",            # Use env vars with this prefix for overrides
    defaults=defaults,         # Provide the default settings defined earlier
    mandatory=mandatory_keys,  # List of keys that must be present after loading
    overrides_dict=cli_overrides  # Final overrides from CLI or other dynamic source
)
```

When this runs, confy will apply each layer in order: start with `defaults`, merge in values from `config.toml`, then load a `.env` (if found and not disabled) into environment, apply any matching environment variables (with prefix `MYAPP_` in this case), and finally apply the `cli_overrides` dictionary values. After constructing `cfg`, you have a fully merged configuration object ready to use, or to validate for required keys.

## Accessing Configuration Values with Dot-Notation

One of confy’s strengths is the ability to access config values using dot notation as if they were attributes of an object. The `Config` object returned by confy behaves like both an object (attribute access) *and* a dictionary.

**Attribute (Dot) Access:** You can access nested config values directly. For example:

```python
# Assuming cfg is loaded as above:
print(f"Database Host: {cfg.database.host}")
print(f"Database Port: {cfg.database.port}")
print(f"Database User: {cfg.database.user}")
print(f"Logging Level: {cfg.logging.level}")
print(f"New Dashboard Enabled: {cfg.feature_flags.new_dashboard}")
```



Each section in the config (like `database`, `logging`, `feature_flags`) is itself a `Config` object, so you can chain attributes. In the example above, `cfg.database.host` refers to the `host` key under the `database` section. This works for as deeply nested structures as needed. If we had loaded the defaults, file, env, and overrides as in the previous sections, these properties would reflect the final resolved value. (For instance, if the CLI overrides set the database port to 5433, `cfg.database.port` would be 5433, overriding the default/file value.)

You can also **set** values or even entire subsections via attribute assignment. For example, `cfg.database.host = "newhost"` would update the configuration in-memory (this won’t write to file unless you explicitly use the CLI `set` command or similar). Deleting a key is supported via `del cfg.logging.format`, for instance, which would remove that key from the config object. Under the hood, `Config` inherits from dict, so it updates accordingly when you set or delete attributes.

**Dictionary-style Access:** The `Config` object supports typical dictionary operations as well. You can call `cfg.get("some.key", default_value)` to safely get a value with a fallback, and you can check membership with the `in` operator. These dictionary methods also accept dot-notation strings for nested keys. For example:

```python
# Safe access with a default:
timeout = cfg.get("network.timeout", 30)  
print(f"Network Timeout: {timeout}")       # If network.timeout is not set, prints 30

# Check for existence of a nested key:
if "secrets.api_key" in cfg:
    print(f"API Key found: {cfg.secrets.api_key}")
else:
    print("API Key is not configured.")
```



In the snippet above, `cfg.get("network.timeout", 30)` will return 30 if no `network.timeout` key exists in any layer of the config (thus avoiding an AttributeError). The expression `"secrets.api_key" in cfg` checks if `cfg.secrets.api_key` is set (either via defaults, file, env, or overrides). This dual nature (object and dict) makes `Config` very flexible: you can iterate over `cfg.keys()` or `cfg.items()`, convert it to a plain dict, etc., just like a normal dictionary.

**Full Config as dict:** If you need to serialize or inspect the entire configuration, use `cfg.as_dict()`. This returns a deep copy of the configuration as a plain Python dict (with all nested `Config` objects converted to dicts). This is useful for printing the config (e.g., `print(json.dumps(cfg.as_dict(), indent=2))`) or for passing the configuration to code that expects a regular dictionary.

## Validating Mandatory Keys

If you provided a list of `mandatory` keys when creating the `Config`, confy will automatically check that each of those keys has a value in the merged configuration. If any mandatory key is missing, confy raises a `confy.exceptions.MissingMandatoryConfig` error after loading all sources.

For example, if `"database.password"` was in your mandatory list but no default, file, env, or override provided a value for it, the `Config()` constructor will throw `MissingMandatoryConfig`. You should catch this exception to handle it gracefully. The exception has a `missing_keys` attribute listing which keys were not found.

Typically, you would wrap the Config initialization in a try/except to catch such errors and exit or prompt the user. For instance:

```python
from confy.exceptions import MissingMandatoryConfig

try:
    cfg = Config(..., mandatory=mandatory_keys)
except MissingMandatoryConfig as e:
    missing = ", ".join(e.missing_keys)
    print(f"Error: Missing required configuration for {missing}")
    exit(1)
```

This ensures that your application clearly informs the user which settings must be provided (whether via file or environment) if they were omitted. Marking keys as mandatory is a best practice for things like database credentials, API keys, or other critical settings that your app absolutely cannot run without. It’s much better to fail early with a clear error than to proceed with an incomplete config.

## Using confy with CLI Applications (Argparse Integration)

Many Python applications use command-line interfaces (CLI) and parse arguments with modules like `argparse` or `click`. Confy is designed to integrate easily with such CLI parsers. In fact, it provides a helper function `load_config_from_args` to streamline usage with **argparse**.

This helper will add confy-specific arguments (for config file, prefix, overrides) to your argument parser, parse them, and then initialize a `Config` for you – leaving the rest of your arguments untouched for your app’s own use. This means you can add standard flags like `--config settings.toml` or `--prefix MYAPP` to your script without writing much extra code.

Below is an example of integrating confy into an argparse-based CLI script:

```python
import argparse
from confy.loader import Config
from confy.argparse_integration import load_config_from_args

# 1. Define application-specific defaults and mandatory keys
app_defaults = {"server": {"port": 8080, "workers": 4},
               "logging": {"level": "INFO"}}
app_mandatory = ["server.port"]  # e.g., server.port must be set

# 2. Set up the argument parser for your application
parser = argparse.ArgumentParser(description="My Awesome Application")
parser.add_argument("--workers", type=int, help="Override number of worker processes.")
parser.add_argument("--enable-feature-x", action="store_true", help="Enable experimental feature X.")
# ... add other app-specific arguments as needed ...

# 3. Let confy add its own arguments (--config, --prefix, --overrides) and load the Config
cfg = load_config_from_args(defaults=app_defaults, mandatory=app_mandatory)
# (The above call internally adds --config, --prefix, --overrides, parses them from sys.argv,
#  and uses them along with app_defaults and app_mandatory to create `cfg`.)

# 4. Parse the remaining arguments (those not handled by confy) as usual
args = parser.parse_args()

# 5. Apply any of your own CLI args as overrides if needed
if args.workers is not None:
    cfg.server.workers = args.workers         # override the workers count
if args.enable_feature_x:
    cfg.features.feature_x_enabled = True     # set a feature flag

print(f"Starting server on port {cfg.server.port} with {cfg.server.workers} workers.")
if cfg.get("features.feature_x_enabled"):
    print("Feature X is ENABLED.")
print(f"Logging level set to: {cfg.logging.level}")
```



Let’s break down what’s happening in that code:

- We define `app_defaults` and `app_mandatory` for our application (just like earlier sections).
- We create an argparse `parser` and add our application’s specific arguments (`--workers` and `--enable-feature-x` in this example).
- We call `load_config_from_args(...)` **before** parsing our own args. This function internally creates its own parser to handle `--config`, `--prefix`, and `--overrides` arguments (so you don’t have to add those yourself). It parses those if present in `sys.argv`, builds an `overrides_dict` from the `--overrides` string (which expects comma-separated `dot.key:json_value` pairs), and then calls `Config()` to instantiate our configuration object `cfg` with the given defaults, mandatory keys, and any values from `--config` (file path), `--prefix`, and `--overrides`. Essentially, by the time `load_config_from_args` returns, `cfg` is a fully loaded Config just as if we manually did all the steps.
- Then we parse the remaining arguments with `parser.parse_args()`. The confy helper ensures that only its three options are consumed earlier, so `args` here contains only `--workers` and `--enable-feature-x` (and any other app-specific args).
- We then optionally take the parsed `args` and update the confy config object if needed. In the example, if `--workers 16` was provided, we set `cfg.server.workers = 16` so that it overrides anything that might have been in the config sources. We do similarly for the feature flag. (You could also have passed these in via the initial `--overrides` string to confy instead of separate args – either approach works. Using explicit args and updating `cfg` gives you more control and type safety via argparse.)
- Finally, we use `cfg` in the application (printing out the settings in this case, or proceeding to start a server using those configurations).

The confy argparse integration saves effort by not requiring you to manually wire up `--config` or environment variable prefix handling. It’s particularly useful for CLI tools. By default, it uses the same precedence rules (defaults < file < .env < env < overrides). The `load_config_from_args` function assumes standard names for those arguments, but you can always not use it and parse everything yourself – then call `Config()` with the parsed values (the Quickstart example earlier demonstrated manually constructing `overrides_dict` and calling `Config`).

**Note:** If using the Click library for CLI, confy doesn’t have a dedicated helper like argparse’s, but you can achieve the same by manually collecting `--config`, `--prefix`, etc., or by parsing a combined overrides option and then calling `Config`. The concept of final dictionary overrides works the same way with any CLI parser – simply build a dict of overrides and pass it in.

## Using the **confy** Command-Line Tool

In addition to the Python library, confy comes with a powerful CLI tool (installed as `confy`). This tool allows you to directly inspect or modify configuration files without writing any Python code, which is great for quick checks or scripting.

To use it, run `confy [OPTIONS] COMMAND [ARGS]...`. The CLI supports the same source layers (defaults, config file, .env, env vars, overrides) via **global options**, and then executes a subcommand to either query or change the config.

**Common global options:**

- **`-c, --config PATH`** – Path to the primary JSON or TOML config file to load.
- **`-p, --prefix TEXT`** – Prefix for environment variables (case-insensitive) to consider as overrides (e.g. `--prefix MYAPP`).
- **`--overrides TEXT`** – A comma-separated list of override entries in the format `dot.key:JSON_value`. For example: `--overrides "logging.level:\"DEBUG\",feature_flags.new_dashboard:true"` to override the logging level and a feature flag on the fly.
- **`--defaults PATH`** – Path to a JSON file containing default configuration values (these will load with lowest precedence).
- **`--mandatory TEXT`** – Comma-separated list of mandatory keys that must exist. If after loading the sources those keys are missing, the tool will report an error.
- **`--dotenv-path PATH`** – Specify a custom `.env` file to load (instead of searching for `.env`).
- **`--no-dotenv`** – Disable automatic loading of any `.env` file.

These options let you configure how the configuration is assembled **before** the command runs. For example, you might use `-c production.toml -p MYAPP` in a production environment, or add a `--defaults base_config.json` that always loads a baseline config. (The precedence rules outlined earlier apply: defaults → file → .env → env → overrides.)

**Available subcommands:**

Once the configuration is loaded (according to the options above), the CLI can perform a number of actions on it:

- **`get <KEY>`** – Retrieve the final value of a specific configuration key and print it as JSON. The key is given in dot-notation. If the key isn’t found in the merged config, it will exit with an error code. This is useful for quickly checking what value a certain config ended up as.
- **`set <KEY> <VALUE>`** – Set a configuration key to a new value and write it **back to the source file** (the file specified by `-c`). The value should be given in JSON-compatible format (e.g., string values in quotes). This command will load the config, apply the change, and then write out the entire config file with the updated value, preserving the original JSON/TOML format. **Caution:** This modifies your config file in place – ensure you have backups or version control before scripting mass updates.
- **`exists <KEY>`** – Check if a given key exists in the final merged configuration. The command returns an exit code 0 if the key exists (and prints “true”), or exit code 1 if it doesn’t (printing “false”). This is handy for shell scripts that need to make decisions based on whether something is configured.
- **`search [--key <PAT>] [--val <PAT>]`** – Search the configuration for keys or values matching a pattern. You can provide a substring, glob, or regex pattern, and optionally make it case-insensitive (`-i`). For example, you can find all keys containing “database” or all values that are `"true"`. It will output a JSON snippet of the matching keys/values.
- **`dump`** – Print the entire merged configuration as a prettified JSON object. This shows you exactly what confy sees after applying all layers. It’s useful for debugging or exporting the current effective config.
- **`convert --to <format>`** – Output the merged configuration in a specified format (JSON or TOML). You can direct this output to a file using the `--out FILE` option, effectively allowing you to convert between JSON/TOML. Confy uses `tomli-w` to ensure TOML output is standards-compliant.

For example, suppose we have the earlier `config.toml`, and an environment variable `MYAPP_DATABASE_HOST` set. We can use `confy` to inspect and modify it:

```bash
# Getting a value
$ confy -c config.toml -p MYAPP get database.host
"prod.db.example.com"
```



The above command loads `config.toml`, applies any `MYAPP_...` env vars (overriding the host if `MYAPP_DATABASE_HOST` is set), and then prints out the final `database.host` in JSON format. If that env var was present, this output would reflect it; otherwise it shows the file’s value (`"prod.db.example.com"` in this case).

Now, to override a value via the CLI:

```bash
# Setting a new port in the config file
$ confy -c config.toml set database.port 5435
Set database.port = 5435 in config.toml
```

After running the `set` command, the `database.port` in `config.toml` would be updated to 5435 (and confy ensures the file remains valid TOML). As noted, this writes to disk, so use it carefully (confy will preserve comments and formatting where possible thanks to tomli-w).

You can also combine operations. For instance, to check if a key exists and then perhaps use it in a shell script:

```bash
$ confy -c config.toml exists logging.level && echo "Logging level is set"
true
Logging level is set
```

Or to dump the entire config for review:

```bash
$ confy -c config.toml -p MYAPP dump
{
  "database": {
    "host": "prod.db.example.com",
    "port": 5435,
    "user": "env_db_user"
  },
  "logging": {
    "level": "WARNING",
    "format": "default"
  },
  "feature_flags": {
    "new_dashboard": true,
    "beta_feature": true
  },
  "secrets": {
    "api_key": "dotenv_abc123xyz"
  }
}
```

*(The above JSON output is an example of what `dump` might show after we applied the environment overrides and set a new port – `user` came from the .env, `beta_feature` from an env var, `new_dashboard` perhaps from an override, etc.)*

In summary, the confy CLI tool is great for quick inspections (`get`, `dump`, `search`) and on-the-fly edits (`set`, `convert`). It respects the same layering system, so you can, for example, provide `--defaults` and `--overrides` to the CLI just like in code. Always be careful with `set` since it writes files in-place (make sure to backup or use version control).

## Multi-App Configuration (v0.4.0)

When building an ecosystem of packages that share configuration (e.g., llmcore + semantiscan), confy supports loading per-application defaults, multi-file config merging, and per-app environment variable routing — all from a single `Config` instance.

### Registering App Defaults

Each package in your ecosystem provides its own defaults dict. Register them via `app_defaults`:

```python
from confy.loader import Config

MYAPP_DEFAULTS = {"port": 8080, "debug": False}
WORKER_DEFAULTS = {"threads": 4, "timeout": 30}

cfg = Config(
    app_defaults={
        "myapp": MYAPP_DEFAULTS,
        "worker": WORKER_DEFAULTS,
    },
    file_path="~/.config/myapp/config.toml",
    load_dotenv_file=False,
)
```

App defaults are merged at the lowest precedence — any file, env var, or override will take priority.

### Multi-File Loading

Use `file_paths` to merge multiple config files in order (later files override earlier ones):

```python
cfg = Config(
    app_defaults={"myapp": MYAPP_DEFAULTS},
    file_paths=[
        "defaults.toml",                        # Loaded first (lowest priority)
        ("project.toml", "myapp"),               # Namespaced: contents go under cfg.myapp.*
        "~/.config/myapp/user_overrides.toml",   # Loaded last (highest priority)
    ],
)
```

The tuple form `("project.toml", "myapp")` is useful when a file contains flat keys (e.g., `chunk_size = 2000`) that should be nested under a specific namespace. If the file already has `[myapp]` as a top-level section, confy detects this automatically and doesn't double-nest.

### App-Specific Environment Variable Prefixes

Use `app_prefixes` to route environment variables with app-specific prefixes into the correct namespace:

```python
cfg = Config(
    app_defaults={
        "myapp": {"port": 8080},
        "worker": {"threads": 4},
    },
    prefix="GLOBAL",                      # GLOBAL_* → root config
    app_prefixes={
        "myapp": "MYAPP",                 # MYAPP_PORT=9090 → cfg.myapp.port = 9090
        "worker": "WORKER",               # WORKER_THREADS=8 → cfg.worker.threads = 8
    },
)
```

Use double underscore (`__`) for underscored keys: `MYAPP_MAX__REQUEST__SIZE=1024` → `cfg.myapp.max_request_size = 1024`.

### Accessing App Config

Two equivalent access patterns:

```python
# Via app() accessor — safe, returns empty Config for unknown names
cfg.app("myapp").port        # → 8080
cfg.app("unknown")           # → Config({}) — empty, no error

# Via direct attribute — same result, but raises AttributeError for unknown names
cfg.myapp.port               # → 8080
cfg.nonexistent.key           # → AttributeError
```

Use `cfg.app("name").as_dict()` to get a plain `dict` suitable for passing to libraries that don't accept `Config` objects.

### Example: Wairu Ecosystem

The Wairu ecosystem (llmcore, semantiscan) uses a single TOML file:

```toml
[llmcore]
default_provider = "ollama"

[llmcore.providers.ollama]
default_model = "gemma3:1b"
timeout = 120

[logging]
console_enabled = false
file_enabled = true
file_mode = "single"
display_min_level = "INFO"

[semantiscan.chunking]
chunk_size = 2000
chunk_overlap = 300

[semantiscan.retrieval]
top_k = 15
```

Loaded with:

```python
cfg = Config(
    app_defaults={
        "semantiscan": SEMANTISCAN_DEFAULTS,
    },
    file_path="~/.config/llmcore/config.toml",
    prefix="LLMCORE",
    app_prefixes={"semantiscan": "SEMANTISCAN"},
)

# All apps configured from one file
cfg.llmcore.default_provider                 # → "ollama"
cfg.app("semantiscan").chunking.chunk_size   # → 2000
cfg.logging.file_mode                        # → "single"
```

## Provenance Tracking (v0.4.0)

When debugging "why is this value X?", enable provenance tracking to trace how each config key was set and overridden:

```python
cfg = Config(
    defaults={"db": {"host": "localhost", "port": 5432}},
    file_path="config.toml",       # Contains [db] port = 3306
    prefix="MYAPP",                # MYAPP_DB_PORT=5555 is set in env
    track_provenance=True,
)
```

### Querying Provenance

```python
# Where did db.port end up?
p = cfg.provenance("db.port")
print(p)
# db.port = 5555  ← env:MYAPP_*

# Full override chain (oldest first)
for entry in cfg.provenance_history("db.port"):
    print(f"  {entry.source}: {entry.value}")
# Output:
#   defaults: 5432
#   file:config.toml: 3306
#   env:MYAPP_*: 5555

# Dump all provenance
for key, source in sorted(cfg.provenance_dump().items()):
    print(f"  {key} ← {source}")
```

### Source Labels

Provenance entries use these source label formats:

| Source | Format | Example |
|---|---|---|
| App defaults | `app_defaults:name` | `app_defaults:semantiscan` |
| User defaults | `defaults` | `defaults` |
| Config file | `file:/path/to/file` | `file:/home/user/.config/llmcore/config.toml` |
| Environment | `env:PREFIX_*` | `env:LLMCORE_*` |
| App env prefix | `app_env:PREFIX_*` | `app_env:SEMANTISCAN_*` |
| Overrides dict | `overrides_dict` | `overrides_dict` |

### Performance

Provenance tracking is disabled by default (`track_provenance=False`). When disabled, there is zero overhead. When enabled, the overhead is one dict write per merged key — negligible for typical configs (<500 keys, <50KB memory).

## Best Practices and Common Pitfalls

To get the most out of confy and avoid common issues, consider the following tips:

- **Always provide defaults for optional settings:** By using a `defaults` dict, you ensure your application has baseline values. This prevents issues where a completely missing config might cause runtime errors. Defaults are the foundation of your configuration.
- **Use mandatory keys for critical settings:** Mark truly required settings (like credentials, hostnames, etc.) as `mandatory`. This way confy will alert you on startup if they aren’t provided, and you can fail fast with a clear error message.
- **Plan your prefix strategy:** It’s often best to set a `prefix` for env vars (e.g., your app name or acronym) to avoid picking up unrelated environment variables. If you set `prefix=None` to allow all env vars, be cautious – any env var with a matching name could override your config. Using a prefix like `MYAPP` or `APP_` isolates overrides to only those meant for your app.
- **Double-underscore for nested keys:** Remember to use `__` in environment variable names for keys that have an underscore or to separate words in key names. For example, to target `feature_flags.new_dashboard`, use `MYAPP_FEATURE_FLAGS__NEW_DASHBOARD`. A single underscore would create a dot (new section or key) whereas double underscore yields a literal underscore in the resulting key.
- **Understand `.env` file precedence:** The automatically loaded `.env` file is a convenience for development, but it won’t override real environment variables that are already set. In production, you might not use `.env` at all, relying on actual env vars. If you do use `.env`, know that if something isn’t changing when you expect, it might be because that env var is already defined outside. You can disable `.env` loading with `load_dotenv_file=False` or `--no-dotenv` if it’s not appropriate in certain environments.
- **Quote string values in CLI overrides:** When using the `--overrides` option in the CLI or setting a value with the CLI `set` command, remember that confy parses values as JSON. So the general rule is: for strings, wrap them in quotes. For example, use `--overrides "logging.format:\"simple\""` to ensure `"simple"` is interpreted as a string, or in `confy set logging.format '"simple"'`. If you forget, confy will likely throw a JSON parse error or interpret an unquoted word as something unintended. Numeric and boolean values can be unquoted (e.g., `feature_flags.new_dashboard:true` is fine, and `5435` is fine as a number).
- **Check types of environment values:** Because confy auto-parses JSON, strings like `true`, `false`, or `null` (without quotes) in environment variables will not be strings but booleans or None. If you intended them to be strings, put them in quotes in the `.env` or actual environment (`MYAPP_MODE='"false"'` if you literally need the string "false"). This behavior is helpful (you get proper booleans and numbers), just be mindful of it.
- **Leverage the CLI for debugging:** If your app isn’t picking up a config as expected, use `confy dump` or `confy get` to see what the final configuration looks like outside of your code. This can help pinpoint whether an env var isn’t being recognized (maybe the prefix is wrong) or a file value isn’t loading.
- **Be careful with `confy set`:** The `set` subcommand will modify your config file on disk. Always ensure you know which file you’re targeting with `-c`. It’s wise to keep backups or use version control for your config files, especially if you use `set` in automated scripts.
- **Handle errors in code:** Wrap your confy `Config()` initialization in try/except to handle missing files or missing keys. For example, if you expect a config file to be present, decide if your app should warn or exit when it’s not found (`FileNotFoundError`). Similarly, catch `MissingMandatoryConfig` to guide the user on setting required values. Also be prepared to catch `RuntimeError` which will wrap JSON/TOML parsing errors (indicating your config file might have a syntax mistake). Confy will raise these exceptions, but it’s up to your app to log them and exit or recover as appropriate.
- **Use `cfg.get()` for optional settings:** If some config keys are truly optional (and don’t need a default in all cases), use `cfg.get("key", fallback)` when accessing them to avoid exceptions if they’re missing. This provides a default at the access site. For example, `timeout = cfg.get("network.timeout", 30)` as shown earlier, so if no timeout was configured, it uses 30.
- **Convert to dict when needed:** If you need to serialize or deep-copy the configuration, use `cfg.as_dict()`. This will give you a clean dictionary without any of confy’s behavior attached. It’s especially useful if you want to, say, output the config via JSON in a web response, or pass it to a library that expects a plain dict.

By following these practices, you can smoothly integrate confy into your project and have a robust configuration management system. Confy’s ability to merge multiple sources with clear rules, along with the convenience of dot notation and a CLI tool, can greatly simplify handling config in Python applications of all sizes. Keep this guide handy as you set up confy, and happy configuring!
