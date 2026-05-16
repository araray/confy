# confy/argparse_integration.py
"""
confy.argparse_integration
--------------------------
Optional helper if you want a quick argparse→Config integration.

Functions:
  - build_arg_parser()
  - load_config_from_args(...)
"""

import argparse
import json
import warnings

from .loader import Config


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Argparse helper for confy")
    parser.add_argument("--config", help="Path to JSON or TOML config file")
    parser.add_argument("--prefix", help="Env-var prefix for overrides")
    parser.add_argument("--overrides", help="Comma-separated dot:key,val pairs")
    return parser


def load_config_from_args(defaults=None, mandatory=None):
    """
    Parse known args and return a Config.
    Use in your scripts if you want to piggy-back off argparse.

    Behavioral notes
    ----------------
    * Malformed override pairs (no ``:``) emit a :class:`UserWarning` and
      are skipped (I-07 fix — parity with the Click CLI's yellow warning).
    * ``env_remap_fallback="flat"`` is passed to :class:`Config` so that
      unmatched env vars get deterministic flat-key fallback semantics,
      independent of whether ``load_dotenv_file`` defaults to True
      (I-05 fix). This avoids the surprise where switching .env loading
      on or off silently changes the nesting depth of new env-only keys.
    """
    parser = build_arg_parser()
    args, _ = parser.parse_known_args()
    overrides_dict = {}
    if args.overrides:
        for pair in args.overrides.split(","):
            if ":" in pair:
                k, v = pair.split(":", 1)
                try:
                    overrides_dict[k.strip()] = json.loads(v.strip())
                except json.JSONDecodeError:
                    overrides_dict[k.strip()] = v.strip()
            else:
                # I-07: parity with the Click CLI, which prints a yellow
                # warning to stderr. Here we surface it via Python's
                # ``warnings`` machinery so callers can capture it with
                # :func:`warnings.catch_warnings` or via :mod:`pytest`'s
                # ``recwarn`` fixture.
                warnings.warn(
                    f"Malformed override {pair!r}. "
                    "Use 'key:json_value' format. Pair skipped.",
                    UserWarning,
                    stacklevel=2,
                )
    return Config(
        file_path=args.config,
        prefix=args.prefix,
        overrides_dict=overrides_dict,
        defaults=defaults,
        mandatory=mandatory,
        # I-05: explicit flat fallback so this helper is deterministic
        # regardless of the (defaulted) ``load_dotenv_file`` setting.
        env_remap_fallback="flat",
    )
