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


def _match(
    pattern: str,
    text: str,
    ignore_case: bool = False,
    mode: str = "auto",
) -> bool:
    """Match ``text`` against ``pattern`` using the requested ``mode``.

    Modes
    -----
    * ``"auto"`` (default) — backward-compatible auto-detection:

        1. Glob if ``pattern`` contains ``*``, ``?``, ``[`` or ``]``.
        2. Regex if ``pattern`` contains other regex-special chars and
           is a valid regex.
        3. Otherwise: exact, case-insensitive equality.

      ``ignore_case=True`` only affects the regex branch under
      ``"auto"`` mode (glob and exact branches are already
      case-insensitive there).
    * ``"regex"`` — always treat the pattern as a regular expression
      (``re.search`` semantics). ``ignore_case`` enables
      :data:`re.IGNORECASE`.
    * ``"glob"`` — always treat the pattern as a glob via
      :func:`fnmatch.fnmatch`. ``ignore_case`` selects
      :func:`fnmatch.fnmatch` (case-insensitive) vs
      :func:`fnmatch.fnmatchcase` (case-sensitive).
    * ``"exact"`` — string equality. ``ignore_case`` controls case
      folding.

    Args:
        pattern: The user-supplied search pattern.
        text:    The candidate string to match against.
        ignore_case: Case-insensitivity flag (semantics vary by mode).
        mode:    Explicit match strategy; see above.

    Returns:
        ``True`` iff the pattern matches ``text`` under the chosen mode.
    """
    # I-08: explicit modes bypass auto-detection.
    if mode == "regex":
        flags = re.IGNORECASE if ignore_case else 0
        try:
            return re.search(pattern, text, flags) is not None
        except re.error:
            # Explicit regex with invalid syntax: no match (rather than
            # silently degrading to substring like the auto path would).
            return False

    if mode == "glob":
        if ignore_case:
            return fnmatch.fnmatch(text.lower(), pattern.lower())
        return fnmatch.fnmatchcase(text, pattern)

    if mode == "exact":
        if ignore_case:
            return text.lower() == pattern.lower()
        return text == pattern

    # ``mode == "auto"`` (or any unknown value): fall through to the
    # historical auto-detection path so existing callers and tests
    # continue to work unchanged.
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
@click.option(
    "--overrides-json",
    "overrides_json",
    help=(
        "JSON object string with overrides; supports compound values "
        "(arrays/objects) without comma-corruption. Keys may use "
        "dot-notation. Applied AFTER --overrides (last wins)."
    ),
)
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
@click.option(
    "--track-provenance",
    is_flag=True,
    default=False,
    help="Enable provenance tracking (records where each config value came from).",
)
@click.pass_context
def cli(
    ctx,
    file_path,
    prefix,
    overrides,
    overrides_json,
    defaults,
    mandatory,
    dotenv_path,
    no_dotenv,
    track_provenance,
):
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
        # I-02: expand ~ and $VAR in the user-supplied path so that --defaults
        # is consistent with --config (which goes through the loader's own
        # path normalization).
        defaults_path = os.path.expandvars(os.path.expanduser(defaults))
        try:
            with open(defaults_path, encoding="utf-8") as f:
                raw_defaults = json.load(f)
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
        else:
            # I-03: friendly error for non-object top-level JSON. The
            # ``Config`` constructor expects a dict for ``defaults=``; null
            # is silently accepted (treated as "no defaults supplied"), but
            # arrays / strings / numbers / booleans would otherwise crash
            # with a confusing ``'X' object has no attribute 'items'`` deep
            # in the merge logic.
            if raw_defaults is None:
                defaults_dict = {}
            elif not isinstance(raw_defaults, dict):
                click.secho(
                    f"Error: --defaults file must contain a JSON object "
                    f"(got {type(raw_defaults).__name__}): {defaults}",
                    fg="red",
                    err=True,
                )
                ctx.exit(1)
            else:
                defaults_dict = raw_defaults

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

    # 2b) I-04: parse --overrides-json. Additive on top of --overrides;
    # last-wins for any keys that appear in both (since --overrides-json
    # is documented as applied AFTER --overrides). The value must be a
    # JSON object string at the top level; nested objects are flattened
    # into dot-keys via :func:`_flatten` so that ``deep_merge``'s
    # per-key semantics apply uniformly regardless of how the user
    # wrote the input (nested form, dot-key form, or a mix).
    if overrides_json:
        try:
            raw_json = json.loads(overrides_json)
        except json.JSONDecodeError as e:
            click.secho(
                f"Error parsing --overrides-json: {e}",
                fg="red",
                err=True,
            )
            ctx.exit(1)
        else:
            if not isinstance(raw_json, dict):
                click.secho(
                    f"Error: --overrides-json must be a JSON object "
                    f"(got {type(raw_json).__name__})",
                    fg="red",
                    err=True,
                )
                ctx.exit(1)
            # Flatten nested structure into dot-keys, then merge into
            # overrides_dict. dict.update gives last-wins semantics, which
            # is the documented precedence (--overrides-json beats
            # --overrides on conflicting paths).
            flat_json = _flatten(raw_json)
            overrides_dict.update(flat_json)

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
            # Provenance tracking
            track_provenance=track_provenance,
        )
    except MissingMandatoryConfig as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        ctx.exit(1)
        raise  # pragma: no cover  -- helps type-checker; unreachable at runtime (ctx.exit raises)
    except FileNotFoundError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        ctx.exit(1)
        raise  # pragma: no cover  -- helps type-checker; unreachable at runtime (ctx.exit raises)
    except Exception as e:  # Catch other potential init errors
        click.secho(f"Error initializing configuration: {e}", fg="red", err=True)
        ctx.exit(1)
        raise  # pragma: no cover  -- helps type-checker; unreachable at runtime (ctx.exit raises)

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
        raise  # pragma: no cover  -- helps type-checker; unreachable at runtime (ctx.exit raises)
    # I-15: the previous ``except TypeError as e:`` handler was removed.
    # ``cfg.get`` for a string dot-key delegates to ``get_by_dot`` which
    # only raises :class:`KeyError` (above) or propagates a genuine
    # programming bug. If a future change starts raising :class:`TypeError`
    # here it should bubble up as an actual stack trace rather than be
    # swallowed with a friendly-looking exit code.

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
    except FileNotFoundError:  # pragma: no cover
        # I-16: defensive only. The pre-check above (``os.path.exists``)
        # rules out the path-does-not-exist case at call-entry time;
        # only a TOCTOU race against an external process deleting the
        # file in the gap between the check and the open would reach
        # this handler. Kept for safety.
        click.secho(f"Error: Config file disappeared: {fp}", fg="red", err=True)
        ctx.exit(1)
    except (tomli.TOMLDecodeError, json.JSONDecodeError) as e:
        click.secho(f"Error reading config file {fp}: {e}", fg="red", err=True)
        ctx.exit(1)
    except Exception as e:  # pragma: no cover
        # I-16: catch-all for unanticipated read errors (permission
        # denied flipping mid-load, I/O error on the underlying device,
        # etc.). Specific decode errors are caught above.
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
    except Exception as e:  # pragma: no cover
        # I-16: ``set_by_dot`` with the default ``create_missing=False``
        # can raise :class:`KeyError` on a missing path, but the
        # ``set`` command builds intermediate dicts via the helper's
        # own logic, so a structural conflict from user input would
        # land here. Kept defensively for visibility.
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
    except Exception as e:  # pragma: no cover
        # I-16: write-side I/O errors (disk full, permission denied,
        # path no longer writable). These are environment-dependent
        # and not exercised by the unit test suite.
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
@click.option(
    "--regex",
    "force_regex",
    is_flag=True,
    default=False,
    help=(
        "Force regex matching for --key/--val patterns (overrides "
        "auto-detection). Mutually exclusive with --glob and --exact."
    ),
)
@click.option(
    "--glob",
    "force_glob",
    is_flag=True,
    default=False,
    help=(
        "Force glob (fnmatch) matching. Mutually exclusive with --regex and --exact."
    ),
)
@click.option(
    "--exact",
    "force_exact",
    is_flag=True,
    default=False,
    help=("Force exact string matching. Mutually exclusive with --regex and --glob."),
)
@click.pass_context
def search(ctx, key_pat, val_pat, ignore_case, force_regex, force_glob, force_exact):
    """
    Search for keys/values matching patterns in the final config.
    At least one of --key or --val must be provided.
    Patterns can be plain text, glob (*?), or regex. Use --regex,
    --glob, or --exact to force a specific match mode (I-08).
    """
    if not (key_pat or val_pat):
        click.secho(
            "Error: Please supply --key and/or --val pattern.", fg="red", err=True
        )
        ctx.exit(1)

    # I-08: resolve mutually-exclusive mode flags.
    mode_flags = [force_regex, force_glob, force_exact]
    if sum(mode_flags) > 1:
        click.secho(
            "Error: --regex, --glob, and --exact are mutually exclusive.",
            fg="red",
            err=True,
        )
        ctx.exit(1)
    if force_regex:
        match_mode = "regex"
    elif force_glob:
        match_mode = "glob"
    elif force_exact:
        match_mode = "exact"
    else:
        match_mode = "auto"

    # Flatten the final Config object (which might include nested Configs)
    flat_config = _flatten(ctx.obj["cfg"])
    found = {}

    for k, v in flat_config.items():
        key_match = True  # Assume match if no key pattern
        val_match = True  # Assume match if no value pattern

        # Check key pattern if provided
        if key_pat:
            key_match = _match(key_pat, k, ignore_case, mode=match_mode)

        # Check value pattern if provided and key matched (or no key pattern)
        if val_pat and key_match:
            # Convert value to string for matching
            val_match = _match(val_pat, str(v), ignore_case, mode=match_mode)

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
    except Exception as e:  # pragma: no cover
        # I-17: defensive only. ``json.dumps`` and ``tomli_w.dumps`` can
        # in principle raise on non-serializable values (e.g. live
        # objects), but the in-memory config that lands here has
        # already been deep-merged and contains only plain Python
        # scalars / containers.
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
        except Exception as e:  # pragma: no cover
            # I-17: write-side I/O failures (disk full, permission
            # denied, path no longer writable). Environment-dependent
            # and not covered by the unit test suite.
            click.secho(
                f"Error writing output to file {out_file}: {e}", fg="red", err=True
            )
            ctx.exit(1)
    else:
        click.echo(output_text)


@cli.command()
@click.argument("key", required=False)
@click.pass_context
def provenance(ctx, key):
    """Show where config values came from.

    Without KEY, shows a summary of how many keys came from each source.
    With KEY (dot-notation), shows the full override history for that key.

    Requires --track-provenance flag on the main confy command.

    Examples:

        confy -c config.toml --track-provenance provenance

        confy -c config.toml --track-provenance provenance database.host
    """
    cfg = ctx.obj["cfg"]
    if not hasattr(cfg, "_provenance") or cfg._provenance is None:
        click.secho(
            "Provenance tracking not enabled. Use --track-provenance flag.",
            fg="yellow",
            err=True,
        )
        ctx.exit(1)
        return  # pragma: no cover  -- unreachable; ctx.exit raises

    if key:
        history = cfg.provenance_history(key)
        if not history:
            click.echo(f"No provenance for key: {key}")
        else:
            click.echo(f"Provenance history for '{key}':")
            for i, entry in enumerate(history, 1):
                marker = "  →" if i < len(history) else "  ★"
                click.echo(f"{marker} {entry.source}: {entry.value!r}")
    else:
        summary = cfg._provenance.sources_summary()
        if not summary:
            click.echo("No provenance data recorded.")
        else:
            click.echo("Config value sources:")
            for source, count in sorted(summary.items()):
                click.echo(f"  {source}: {count} key(s)")


# Make the CLI runnable (for development/testing)
if __name__ == "__main__":
    cli()
