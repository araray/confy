"""
confy.argparse_integration
--------------------------
Optional helper if you want a quick argparse→Config integration.

Functions:
  - build_arg_parser()
  - load_config_from_args(...)
"""

import json
import argparse
from .loader import Config

def build_arg_parser():
    parser = argparse.ArgumentParser(description="Argparse helper for confy")
    parser.add_argument('--config', help="Path to JSON or TOML config file")
    parser.add_argument('--prefix', help="Env-var prefix for overrides")
    parser.add_argument('--overrides', help="Comma-separated dot:key,val pairs")
    return parser

def load_config_from_args(defaults=None, mandatory=None):
    """
    Parse known args and return a Config.
    Use in your scripts if you want to piggy-back off argparse.
    """
    parser = build_arg_parser()
    args, _ = parser.parse_known_args()
    overrides_dict = {}
    if args.overrides:
        for pair in args.overrides.split(','):
            if ':' in pair:
                k, v = pair.split(':', 1)
                try:
                    overrides_dict[k.strip()] = json.loads(v.strip())
                except:
                    overrides_dict[k.strip()] = v.strip()
    return Config(
        file_path=args.config,
        prefix=args.prefix,
        overrides_dict=overrides_dict,
        defaults=defaults,
        mandatory=mandatory
    )
