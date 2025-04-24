# confy

**confy** is a minimal, flexible Python configuration library and CLI tool that makes it easy to:

- Load **JSON** & **TOML** files  
- Access settings via **dot-notation** (`cfg.section.key`)  
- Define **defaults** and enforce **mandatory** keys  
- Override via **environment variables** (`PREFIX_KEY1_KEY2=…`)  
- Override via a **dict** passed by your CLI parser  
- Inspect and **mutate** config files from the command line  

Precedence of values:
```

defaults → config file → environment variables → overrides_dict

```
---

## Table of Contents

1. [Features](#features)  
2. [Installation](#installation)  
3. [Quickstart](#quickstart)  
4. [API Reference](#api-reference)  
   - [`Config` class](#config-class)  
   - [Argparse integration](#argparse-integration)  
5. [CLI Usage](#cli-usage)  
   - [Global options](#global-options)  
   - [Subcommands](#subcommands)  
6. [Advanced Usage](#advanced-usage)  
7. [Additional Utilities](#additional-utilities)  
8. [Testing](#testing)  
9. [Contributing](#contributing)  
10. [License](#license)  

---

## Features

- **File formats**: JSON & TOML  
- **Dot-notation** read/write access  
- **Defaults** and **mandatory** key enforcement  
- **Environment-variable** overrides with a configurable prefix  
- **Dict-based** overrides for seamless CLI integration  
- **Click-based** `confy` CLI for inspecting & mutating configs  
- **Argparse helper** for script-level integration  

---

## Installation

Install via pip:

```bash
pip install confy
```

Or from source:

```bash
git clone https://github.com/your-org/confy.git
cd confy
pip install .
```

------

## Quickstart

```python
from confy.loader import Config
from confy.exceptions import MissingMandatoryConfig

# 1) Define defaults & mandatory keys
defaults = {
    "db": {"host": "localhost", "port": 3306},
    "auth": {"local": {"enabled": False}}
}
mandatory = ["db.host", "db.port", "auth.local.enabled"]

# 2) Parse your CLI (any parser) → build overrides_dict
# e.g. from argparse, click, or custom logic
overrides = {
    "db.port": 5432,
    "auth.local.enabled": True
}

# 3) Initialize Config
try:
    cfg = Config(
        file_path="config.toml",
        prefix="APP_CONF",
        overrides_dict=overrides,
        defaults=defaults,
        mandatory=mandatory
    )
except MissingMandatoryConfig as e:
    print("Configuration error:", e)
    exit(1)

# 4) Access settings via dot notation
print("DB Host:", cfg.db.host)
print("DB Port:", cfg.db.port)
print("Local Auth Enabled:", cfg.auth.local.enabled)
```

------

## API Reference

### `Config` class

Located in `confy/loader.py`.

```python
Config(
    file_path: str = None,
    prefix: str = None,
    overrides_dict: Mapping[str, object] = None,
    defaults: dict = None,
    mandatory: list[str] = None
)
```

- **file_path**: Path to a `.json` or `.toml` file.
- **prefix**: Environment-variable prefix (e.g. `"APP_CONF"`). Looks for `APP_CONF_KEY1_KEY2=…`.
- **overrides_dict**: A plain dict of `{ "dot.key": value }` to apply on top.
- **defaults**: A dict of default settings.
- **mandatory**: A list of dot-notation keys that **must** be defined.

#### Methods & Behavior

- **Attribute access**: `cfg.section.key`
- **`as_dict()`**: Return the full config as a Python dict.
- **Raises** `MissingMandatoryConfig` if any mandatory keys are missing after all merges.

------

### Argparse integration

If you use **argparse** in your project, you can leverage a simple helper in `confy/argparse_integration.py`:

```python
from confy.argparse_integration import load_config_from_args
from confy.exceptions import MissingMandatoryConfig

# in your script:
defaults = {...}
mandatory = [...]
try:
    cfg = load_config_from_args(defaults=defaults,
                                mandatory=mandatory)
except MissingMandatoryConfig as e:
    print("Config error:", e)
    exit(1)

# Now use cfg.db.host, etc.
```

This will parse `--config`, `--prefix`, and `--overrides` flags automatically and return a `Config` instance.

------

## CLI Usage

The `confy` CLI is installed as a console script entry point. It uses **Click** under the hood.

### Global options

```
Usage: confy [OPTIONS] COMMAND [ARGS]...

Options:
  -c, --config PATH     Path to JSON or TOML config file
  -p, --prefix TEXT     Env-var prefix for overrides
  --overrides TEXT      Comma-separated dot:key,value pairs
  --defaults PATH       Path to JSON file containing default values
  --mandatory TEXT      Comma-separated list of mandatory dot-keys
  -h, --help            Show this message and exit.
```

> **Note:** You may combine `--defaults defaults.json`, environment variables, and `--overrides` to shape your final configuration.

### Subcommands

| Command   | Description                                                  |
| --------- | ------------------------------------------------------------ |
| `get`     | Print the value of a dot-key as JSON                         |
| `set`     | Update a dot-key in the file on disk (preserves JSON/TOML format) |
| `exists`  | Exit status 0 if key exists, 1 otherwise                     |
| `search`  | Find keys/values matching a pattern (regex, glob, or exact)  |
| `dump`    | Pretty-print the entire config as JSON                       |
| `convert` | Convert between JSON & TOML                                  |

#### `get`

```bash
confy -c config.toml get auth.local.enabled
```

#### `set`

```bash
confy -c config.toml set db.port 5432
```

#### `exists`

```bash
confy -c config.toml exists some.nested.key
# exit 0 if present, 1 if absent
```

#### `search`

```bash
# search by key pattern
confy -c config.toml search --key 'db.*'

# search by value pattern
confy -c config.toml search --val 'true|false'

# both
confy -c config.toml search --key 'auth.*' --val 'enabled'
```

#### `dump`

```bash
confy -c config.toml dump
```

#### `convert`

```bash
# to JSON
confy -c config.toml convert --to json --out config.json

# to TOML (stdout)
confy -c config.json convert --to toml
```

------

## Advanced Usage

- **Environment overrides**

    ```bash
    export APP_CONF_DB_HOST=prod.db.local
    export APP_CONF_AUTH_LOCAL_ENABLED=true
    confy -c config.toml dump
    ```

- **Chaining defaults, file, env, overrides**

    ```bash
    confy \
      --defaults defaults.json \
      -c config.toml \
      -p APP_CONF \
      --overrides "db.port:6000,feature.flag:true" \
      dump
    ```

- **Error handling**

    ```bash
    if ! confy -c config.toml exists db.host; then
      echo "db.host is required" >&2
      exit 1
    fi
    ```

------

## Additional Utilities (Ideas)

- **`diff`**: Compare two configs and show added/removed/changed keys
- **`validate`**: Check config against JSON Schema or simple rules
- **`env`**: Export current config as shell `export KEY=VAL` statements
- **`repl`**: Interactive prompt for browsing/editing config
- **`encrypt`/`decrypt`**: Plug in secrets handling for encrypted values
- **`template`**: Render config via Jinja2 or another templating engine

------

## Testing

A comprehensive `pytest` suite is included in `tests/test_loader.py`. To run:

```bash
pytest --maxfail=1 --disable-warnings -q
```

------

## Contributing

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Write code & tests
4. Update `README.md` / docs as needed
5. Commit with clear message (e.g. `feat: add diff subcommand`)
6. Open a pull request

Please adhere to the existing code style and add tests for new features.

------

## License

This project is licensed under the **MIT License**. See LICENSE for details.
