# confy/cli.py

import fnmatch
import json
import os
import re
from typing import Any

import click

# Use tomli for reading (if needed, though Config handles it)
import tomli

# Use tomli_w for writing TOML
import tomli_w

from .exceptions import MissingMandatoryConfig
from .loader import Config, set_by_dot


def _match(pattern: str, text: str, ignore_case: bool = False) -> bool:
    """
    Match text against pattern with:
      • Glob (case-insensitive)
      • Regex (case-sensitive by default, -i to ignore case)
      • Exact (case-insensitive)
    """
    # 1) Glob if it contains *, ?, [ or ]
    if any(c in pattern for c in "*?[]"):
        return fnmatch.fnmatch(text.lower(), pattern.lower())

    # 2) Regex if it contains regex-special chars
    # Added more robust check for regex chars
    if re.search(r"[.^$*+?{}\\|()[\]]", pattern):
        flags = re.IGNORECASE if ignore_case else 0
        try:
            # Check if it's a valid regex pattern
            re.compile(pattern, flags)
            return re.search(pattern, text, flags) is not None
        except re.error:
            # If not a valid regex, treat as plain string for exact match
            pass  # Fall through to exact match

    # 3) Exact match (case-insensitive)
    return text.lower() == pattern.lower()


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested dict into { 'a.b.c': value, … }."""
    items = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            # Ensure we flatten Config objects correctly by using as_dict()
            items.update(_flatten(v.as_dict() if isinstance(v, Config) else v, key))
        elif isinstance(v, list):
            # Handle lists, potentially containing dicts/Config objects
            items[key] = [
                item.as_dict() if isinstance(item, Config) else item for item in v
            ]
        else:
            items[key] = v
    return items


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-c", "--config", "file_path", help="JSON/TOML config file to load.")
@click.option("-p", "--prefix", help="Env-var prefix for overrides (e.g., APP_CONF).")
@click.option("--overrides", help="Comma-sep `key:json_val` pairs for overrides.")
@click.option("--defaults", help="Path to JSON file containing default values.")
@click.option("--mandatory", help="Comma-sep list of mandatory dot-keys.")
# Add options for .env file handling
@click.option("--dotenv-path", help="Explicit path to the .env file to load.")
@click.option(
    "--no-dotenv",
    is_flag=True,
    default=False,
    help="Disable automatic loading of .env file.",
)
@click.pass_context
def cli(ctx, file_path, prefix, overrides, defaults, mandatory, dotenv_path, no_dotenv):
    """
    confy CLI: inspect & mutate JSON/TOML configs via dot-notation.

    Supports defaults, config files (JSON/TOML), .env files, environment
    variables (with prefix), and explicit overrides. Requires Python 3.10+.

    Load a file (`-c config.toml`), then run subcommands:
      • get       KEY
      • set       KEY VAL
      • exists    KEY
      • search    [--key PAT] [--val PAT] [-i]
      • dump
      • convert   [--to json|toml] [--out FILE]
    """
    # 1) load defaults.json if provided
    defaults_dict = {}
    if defaults:
        try:
            with open(defaults, encoding="utf-8") as f:
                defaults_dict = json.load(f)
        except FileNotFoundError:
            click.secho(
                f"Error: Defaults file not found: {defaults}", fg="red", err=True
            )
            ctx.exit(1)
        except json.JSONDecodeError as e:
            click.secho(
                f"Error parsing defaults file {defaults}: {e}", fg="red", err=True
            )
            ctx.exit(1)

    # 2) parse overrides to dict
    overrides_dict = {}
    if overrides:
        for pair in overrides.split(","):
            if ":" in pair:
                k, raw = pair.split(":", 1)
                key_stripped = k.strip()
                val_stripped = raw.strip()
                try:
                    # Try parsing as JSON first
                    overrides_dict[key_stripped] = json.loads(val_stripped)
                except json.JSONDecodeError:
                    # Fallback to string if not valid JSON
                    overrides_dict[key_stripped] = val_stripped
            else:
                # Handle cases where value might be missing (treat as empty string or flag?)
                # For now, we require key:value format
                click.secho(
                    f"Warning: Malformed override '{pair}'. Use 'key:json_value' format.",
                    fg="yellow",
                    err=True,
                )

    # 3) mandatory list
    mandatory_list = [k.strip() for k in mandatory.split(",")] if mandatory else []

    # 4) build Config
    cfg: Config
    try:
        cfg = Config(
            file_path=file_path,
            prefix=prefix,
            overrides_dict=overrides_dict,
            defaults=defaults_dict,
            mandatory=mandatory_list,
            # Pass dotenv options
            load_dotenv_file=not no_dotenv,
            dotenv_path=dotenv_path,
        )
    except MissingMandatoryConfig as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        ctx.exit(1)
        raise  # This line will never execute, but helps type checker
    except FileNotFoundError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        ctx.exit(1)
        raise  # This line will never execute, but helps type checker
    except Exception as e:  # Catch other potential init errors
        click.secho(f"Error initializing configuration: {e}", fg="red", err=True)
        ctx.exit(1)
        raise  # This line will never execute, but helps type checker

    ctx.obj = {
        "cfg": cfg,
        "file_path": file_path,  # Keep track of original file for 'set' command
    }


@cli.command()
@click.argument("key")
@click.pass_context
def get(ctx, key):
    """Print the value of KEY (dot-notation) as JSON."""
    cfg = ctx.obj["cfg"]
    val: Any
    try:
        # Use the Config object's get method which handles dot notation
        val = cfg.get(key)
        if val is None and key not in cfg:  # Distinguish None value from missing key
            raise KeyError(f"Key not found: {key}")
    except KeyError:
        click.secho(f"Key not found: {key}", fg="yellow", err=True)
        ctx.exit(1)
        raise  # This line will never execute, but helps type checker
    except TypeError as e:  # Handle invalid path errors during get
        click.secho(f"Error accessing key '{key}': {e}", fg="red", err=True)
        ctx.exit(1)
        raise  # This line will never execute, but helps type checker

    # Dump the retrieved value as JSON
    click.echo(json.dumps(val, indent=2))


@cli.command()
@click.argument("key")
@click.argument("value")
@click.pass_context
def set(ctx, key, value):
    """
    Set KEY to JSON-parsed VALUE in the source config file.
    Writes back to disk, preserving original format (JSON or TOML).
    Requires the --config option to be set.
    """
    fp = ctx.obj["file_path"]
    if not fp:
        click.secho("Error: --config must be provided for `set`", fg="red", err=True)
        ctx.exit(1)
    if not os.path.exists(fp):
        click.secho(f"Error: Config file not found: {fp}", fg="red", err=True)
        ctx.exit(1)

    ext = os.path.splitext(fp)[1].lower()
    data = {}  # Initialize data

    # Read the current file content
    try:
        if ext == ".toml":
            # Use 'rb' mode for tomli
            with open(fp, "rb") as f:
                data = tomli.load(f)
        elif ext == ".json":
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
        else:
            click.secho(
                f"Error: Unsupported file type for set: {ext}", fg="red", err=True
            )
            ctx.exit(1)
    except FileNotFoundError:
        # Should be caught above, but handle defensively
        click.secho(f"Error: Config file disappeared: {fp}", fg="red", err=True)
        ctx.exit(1)
    except (tomli.TOMLDecodeError, json.JSONDecodeError) as e:
        click.secho(f"Error reading config file {fp}: {e}", fg="red", err=True)
        ctx.exit(1)
    except Exception as e:  # Catch other read errors
        click.secho(f"Error loading file {fp} for update: {e}", fg="red", err=True)
        ctx.exit(1)

    # Parse the input value (try JSON first, then string)
    try:
        parsed_value = json.loads(value)
    except json.JSONDecodeError:
        parsed_value = value  # Use raw string if not JSON

    # Set the value in the loaded data structure using dot notation helper
    try:
        set_by_dot(data, key, parsed_value)
    except Exception as e:
        click.secho(f"Error setting key '{key}': {e}", fg="red", err=True)
        ctx.exit(1)

    # Write the modified data back to the file
    try:
        if ext == ".toml":
            # Use 'wb' mode for tomli_w
            with open(fp, "wb") as f:
                tomli_w.dump(data, f)
        elif ext == ".json":
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)  # Keep pretty printing for JSON
    except Exception as e:
        click.secho(f"Error writing updated config to {fp}: {e}", fg="red", err=True)
        ctx.exit(1)

    click.secho(f"Set {key} = {parsed_value!r} in {fp}", fg="green")


@cli.command()
@click.argument("key")
@click.pass_context
def exists(ctx, key):
    """Exit 0 if KEY exists in the final config, 1 otherwise."""
    # Use the Config object's __contains__ which handles dot notation
    if key in ctx.obj["cfg"]:
        click.echo("true")  # Output confirmation for scripting
        ctx.exit(0)
    else:
        click.echo("false")  # Output confirmation for scripting
        ctx.exit(1)


@cli.command()
@click.option("--key", "key_pat", help="Pattern for keys (regex/glob/plain).")
@click.option("--val", "val_pat", help="Pattern for values (regex/glob/plain).")
@click.option(
    "-i",
    "--ignore-case",
    is_flag=True,
    default=False,
    help="Make key/value pattern matching case-insensitive.",
)
@click.pass_context
def search(ctx, key_pat, val_pat, ignore_case):
    """
    Search for keys/values matching patterns in the final config.
    At least one of --key or --val must be provided.
    Patterns can be plain text, glob (*?), or regex.
    """
    if not (key_pat or val_pat):
        click.secho(
            "Error: Please supply --key and/or --val pattern.", fg="red", err=True
        )
        ctx.exit(1)

    # Flatten the final Config object (which might include nested Configs)
    flat_config = _flatten(ctx.obj["cfg"])
    found = {}

    for k, v in flat_config.items():
        key_match = True  # Assume match if no key pattern
        val_match = True  # Assume match if no value pattern

        # Check key pattern if provided
        if key_pat:
            key_match = _match(key_pat, k, ignore_case)

        # Check value pattern if provided and key matched (or no key pattern)
        if val_pat and key_match:
            # Convert value to string for matching
            val_match = _match(val_pat, str(v), ignore_case)

        # If both relevant patterns match, add to results
        if key_match and val_match:
            found[k] = v

    if not found:
        click.echo("No matches found.")
        ctx.exit(1)  # Indicate no matches found via exit code

    # Output found items as JSON
    click.echo(json.dumps(found, indent=2))


@cli.command()
@click.pass_context
def dump(ctx):
    """Pretty-print the entire final config as JSON."""
    # Use the Config object's as_dict() method for clean output
    click.echo(json.dumps(ctx.obj["cfg"].as_dict(), indent=2))


@cli.command()
@click.option(
    "--to",
    "fmt",
    type=click.Choice(["json", "toml"], case_sensitive=False),
    required=True,
    help="Format to convert to (json or toml).",
)
@click.option("--out", "out_file", help="Write output to file (instead of stdout).")
@click.pass_context
def convert(ctx, fmt, out_file):
    """
    Convert the final loaded config to JSON or TOML format.
    """
    # Get the final configuration as a plain dictionary
    data = ctx.obj["cfg"].as_dict()
    output_text = ""

    try:
        if fmt == "toml":
            # Use tomli_w.dumps to generate TOML string
            output_text = tomli_w.dumps(data)
        else:  # fmt == "json"
            output_text = json.dumps(data, indent=2)
    except Exception as e:
        click.secho(f"Error converting config data to {fmt}: {e}", fg="red", err=True)
        ctx.exit(1)

    # Write to file or print to stdout
    if out_file:
        try:
            # Use 'w' mode for text, 'wb' isn't needed for dumps string output
            mode = "w"
            encoding = "utf-8"
            # Ensure directory exists if path includes directories
            os.makedirs(os.path.dirname(out_file), exist_ok=True)
            with open(out_file, mode=mode, encoding=encoding) as f:
                f.write(output_text)
            click.secho(f"Wrote {fmt.upper()} output to {out_file}", fg="green")
        except Exception as e:
            click.secho(
                f"Error writing output to file {out_file}: {e}", fg="red", err=True
            )
            ctx.exit(1)
    else:
        click.echo(output_text)


# Make the CLI runnable (for development/testing)
if __name__ == "__main__":
    cli()
