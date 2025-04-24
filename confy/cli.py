# confy/cli.py

import json
import os
import re
import fnmatch
import click

from .loader import Config, get_by_dot, set_by_dot
from .exceptions import MissingMandatoryConfig

def _match(pattern: str, text: str, ignore_case: bool = False) -> bool:
    """
    Try glob first, then regex, then exact match.
      - Glob if pattern contains *, ?, [ or ]
      - Regex if pattern contains any of . + ^ $ ( ) { } | \
      - Exact otherwise
    Honors ignore_case by lowercasing both pattern & text.
    """
    if ignore_case:
        pattern = pattern.lower()
        text = text.lower()

    # 1) Glob
    if any(c in pattern for c in "*?[]"):
        return fnmatch.fnmatch(text, pattern)

    # 2) Regex
    if any(c in pattern for c in ".+^$(){}|\\"):
        flags = re.IGNORECASE if ignore_case else 0
        return re.search(pattern, text, flags) is not None

    # 3) Exact
    return pattern == text

def _flatten(d: dict, prefix: str = "") -> dict:
    """Flatten nested dict into { 'a.b.c': value, … }."""
    items = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            items.update(_flatten(v, key))
        else:
            items[key] = v
    return items

@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-c", "--config",    "file_path",  help="JSON/TOML file to load")
@click.option("-p", "--prefix",    help="Env-var prefix for overrides")
@click.option("--overrides",       help="Comma-sep `key:json_val` pairs")
@click.option("--defaults",        help="Path to JSON defaults (optional)")
@click.option("--mandatory",       help="Comma-sep list of mandatory dot-keys")
@click.pass_context
def cli(ctx, file_path, prefix, overrides, defaults, mandatory):
    """
    confy CLI: inspect & mutate JSON/TOML configs via dot-notation.

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
        with open(defaults, "r") as f:
            defaults_dict = json.load(f)

    # 2) parse overrides to dict
    overrides_dict = {}
    if overrides:
        for pair in overrides.split(","):
            if ":" in pair:
                k, raw = pair.split(":", 1)
                try:
                    overrides_dict[k.strip()] = json.loads(raw.strip())
                except:
                    overrides_dict[k.strip()] = raw.strip()

    # 3) mandatory list
    mandatory_list = mandatory.split(",") if mandatory else []

    # 4) build Config
    try:
        cfg = Config(
            file_path=file_path,
            prefix=prefix,
            overrides_dict=overrides_dict,
            defaults=defaults_dict,
            mandatory=mandatory_list
        )
    except MissingMandatoryConfig as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        ctx.exit(1)

    ctx.obj = {
        "cfg": cfg,
        "file_path": file_path,
    }

@cli.command()
@click.argument("key")
@click.pass_context
def get(ctx, key):
    """Print the value of KEY (dot-notation) as JSON."""
    cfg = ctx.obj["cfg"]
    try:
        val = get_by_dot(cfg.as_dict(), key)
    except KeyError:
        click.secho(f"Key not found: {key}", fg="yellow", err=True)
        ctx.exit(1)
    click.echo(json.dumps(val, indent=2))

@cli.command()
@click.argument("key")
@click.argument("value")
@click.pass_context
def set(ctx, key, value):
    """
    Set KEY to JSON-parsed VALUE in the source file.
    Writes back to disk (same format: JSON or TOML).
    """
    fp = ctx.obj["file_path"]
    if not fp:
        click.secho("Error: --config must be provided for `set`", fg="red", err=True)
        ctx.exit(1)

    ext = os.path.splitext(fp)[1].lower()
    with open(fp, "r") as f:
        if ext == ".toml":
            import toml as _toml
            data = _toml.load(f)
        else:
            data = json.load(f)

    try:
        parsed = json.loads(value)
    except:
        parsed = value
    set_by_dot(data, key, parsed)

    with open(fp, "w") as f:
        if ext == ".toml":
            import toml as _toml
            f.write(_toml.dumps(data))
        else:
            json.dump(data, f, indent=2)

    click.secho(f"Set {key} = {parsed!r} in {fp}", fg="green")

@cli.command()
@click.argument("key")
@click.pass_context
def exists(ctx, key):
    """Exit 0 if KEY exists in config, 1 otherwise."""
    try:
        get_by_dot(ctx.obj["cfg"].as_dict(), key)
        click.echo("true")
        ctx.exit(0)
    except KeyError:
        click.echo("false")
        ctx.exit(1)

@cli.command()
@click.option("--key", "key_pat",    help="Pattern for keys (regex/glob/plain)")
@click.option("--val", "val_pat",    help="Pattern for values (regex/glob/plain)")
@click.option("-i", "--ignore-case", is_flag=True,
              help="Make key/value matching case-insensitive")
@click.pass_context
def search(ctx, key_pat, val_pat, ignore_case):
    """
    Search for keys/values matching patterns.
    At least one of --key or --val must be provided.
    """
    if not (key_pat or val_pat):
        click.secho("Error: supply --key or --val", fg="red", err=True)
        ctx.exit(1)

    flat = _flatten(ctx.obj["cfg"].as_dict())
    found = {}
    for k, v in flat.items():
        ks = _match(key_pat, k, ignore_case) if key_pat else True
        vs = _match(val_pat, str(v), ignore_case) if val_pat else True
        if ks and vs:
            found[k] = v

    if not found:
        click.echo("No matches")
        ctx.exit(1)

    click.echo(json.dumps(found, indent=2))

@cli.command()
@click.pass_context
def dump(ctx):
    """Pretty-print the entire config as JSON."""
    click.echo(json.dumps(ctx.obj["cfg"].as_dict(), indent=2))

@cli.command()
@click.option("--to", "fmt", type=click.Choice(["json","toml"]), default="json",
              help="Format to convert to")
@click.option("--out", "out_file", help="Write to file (instead of stdout)")
@click.pass_context
def convert(ctx, fmt, out_file):
    """
    Convert loaded config to JSON or TOML.
    """
    data = ctx.obj["cfg"].as_dict()
    if fmt == "toml":
        import toml as _toml
        text = _toml.dumps(data)
    else:
        text = json.dumps(data, indent=2)

    if out_file:
        with open(out_file, "w") as f:
            f.write(text)
        click.secho(f"Wrote {fmt.upper()} to {out_file}", fg="green")
    else:
        click.echo(text)
