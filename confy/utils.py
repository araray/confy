# confy/utils.py
"""
confy.utils
-----------

Shared utility functions for path handling and other common operations.
Used internally by confy and available for downstream consumers.
"""

import os
from pathlib import Path
from typing import Optional


def expand_path(path: Optional[str]) -> Optional[str]:
    """Expand ~ and environment variables in a path string.

    Handles both user home directory expansion (~) and environment
    variable expansion ($VAR, ${VAR}).

    Args:
        path: Path string to expand, or None.

    Returns:
        Expanded path string, or None if input was None.

    Examples:
        >>> expand_path("~/configs/app.toml")
        '/home/user/configs/app.toml'
        >>> expand_path("$HOME/.config/app.toml")
        '/home/user/.config/app.toml'
        >>> expand_path(None)
        None
    """
    if path is None:
        return None
    return os.path.expandvars(os.path.expanduser(path))


def resolve_path(path: Optional[str]) -> Optional[Path]:
    """Expand and resolve a path to an absolute Path object.

    Combines expand_path() with Path.resolve() to produce a fully
    qualified, absolute path with all symlinks resolved.

    Args:
        path: Path string, or None.

    Returns:
        Resolved absolute Path, or None if input was None.

    Examples:
        >>> resolve_path("~/configs/../configs/app.toml")
        PosixPath('/home/user/configs/app.toml')
        >>> resolve_path(None)
        None
    """
    expanded = expand_path(path)
    if expanded is None:
        return None
    return Path(expanded).resolve()
