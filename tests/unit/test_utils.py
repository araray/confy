# tests/unit/test_utils.py
"""Unit tests for :mod:`confy.utils`.

Specification reference
-----------------------
* ``CONFY_DESIGN_SPECIFICATION.md`` §5.3.1, §8.2 — Path Handling
* ``confy/utils.py``: :func:`expand_path`, :func:`resolve_path`

Why this file exists
--------------------
The existing ``tests/v040/test_phase0_foundation.py`` covers the happy paths
(``~`` expansion, ``$VAR`` expansion, ``None`` passthrough). What's missing
and important:

* **Missing environment variable** — what does ``$DOES_NOT_EXIST/foo`` do?
  The implementation defers to :func:`os.path.expandvars`, which leaves
  the literal ``$VAR`` token in place. Downstream code relies on this.
* **Combined expansion** — ``~/$VAR/file`` must work in one pass.
* **Empty string** — neither ``""`` nor :func:`os.path.expandvars` raise on
  empty input; verify behavior is identity.
* **No-op paths** — paths without ``~`` or ``$`` must pass through unchanged.
* **Resolve on empty / relative** — :func:`resolve_path` resolves against
  the *current* CWD; empty input gives CWD itself.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from confy.utils import expand_path, resolve_path

pytestmark = pytest.mark.unit


# =============================================================================
# expand_path
# =============================================================================


class TestExpandPathNone:
    def test_returns_none_for_none(self) -> None:
        assert expand_path(None) is None


class TestExpandPathBraced:
    """Both ``$VAR`` and ``${VAR}`` forms are supported by expandvars."""

    def test_unbraced_var(self, monkeypatch) -> None:
        monkeypatch.setenv("CONFY_TEST_DIR", "/opt/configs")
        assert expand_path("$CONFY_TEST_DIR/app.toml") == "/opt/configs/app.toml"

    def test_braced_var(self, monkeypatch) -> None:
        monkeypatch.setenv("CONFY_TEST_DIR", "/opt/configs")
        assert expand_path("${CONFY_TEST_DIR}/app.toml") == "/opt/configs/app.toml"

    def test_var_at_end(self, monkeypatch) -> None:
        monkeypatch.setenv("CONFY_TEST_DIR", "/opt/configs")
        assert expand_path("/prefix/$CONFY_TEST_DIR") == "/prefix//opt/configs"


class TestExpandPathMissingVar:
    """Missing env vars pass through verbatim — this is :func:`os.path.expandvars`
    behavior. Confy inherits it and downstream code (including the file-path
    handling in :class:`Config`) depends on it.
    """

    def test_missing_unbraced_left_as_literal(self, monkeypatch) -> None:
        monkeypatch.delenv("CONFY_DEFINITELY_UNSET", raising=False)
        result = expand_path("$CONFY_DEFINITELY_UNSET/foo")
        assert result == "$CONFY_DEFINITELY_UNSET/foo"

    def test_missing_braced_left_as_literal(self, monkeypatch) -> None:
        monkeypatch.delenv("CONFY_DEFINITELY_UNSET", raising=False)
        result = expand_path("${CONFY_DEFINITELY_UNSET}/foo")
        assert result == "${CONFY_DEFINITELY_UNSET}/foo"

    def test_partial_expansion(self, monkeypatch) -> None:
        """If one var resolves and another doesn't, only the resolvable one
        is expanded; the other is left literal.
        """
        monkeypatch.setenv("CONFY_TEST_RESOLVED", "/resolved")
        monkeypatch.delenv("CONFY_UNRESOLVED", raising=False)
        result = expand_path("$CONFY_TEST_RESOLVED/$CONFY_UNRESOLVED")
        assert result == "/resolved/$CONFY_UNRESOLVED"


class TestExpandPathTilde:
    """``~`` and ``~user`` expansion via :func:`os.path.expanduser`."""

    def test_tilde_uses_home(self, monkeypatch) -> None:
        monkeypatch.setenv("HOME", "/home/testuser")
        assert expand_path("~/configs/app.toml") == "/home/testuser/configs/app.toml"

    def test_tilde_alone(self, monkeypatch) -> None:
        monkeypatch.setenv("HOME", "/home/testuser")
        assert expand_path("~") == "/home/testuser"

    def test_tilde_not_at_start_is_literal(self, monkeypatch) -> None:
        """``foo/~/bar`` is NOT a tilde expansion (the ~ isn't at start of
        a path component in expanduser's recognized form).
        """
        monkeypatch.setenv("HOME", "/home/testuser")
        result = expand_path("/abs/~/sub")
        # POSIX expanduser leaves embedded ~ alone.
        assert result == "/abs/~/sub"


class TestExpandPathCombined:
    """Tilde + env var in one path, both applied."""

    def test_tilde_then_var(self, monkeypatch) -> None:
        monkeypatch.setenv("HOME", "/home/testuser")
        monkeypatch.setenv("CONFY_SUB", "configs")
        result = expand_path("~/$CONFY_SUB/app.toml")
        assert result == "/home/testuser/configs/app.toml"


class TestExpandPathNoOp:
    """Paths without expansion markers pass through unchanged."""

    @pytest.mark.parametrize(
        "path",
        [
            "/absolute/path/config.toml",
            "relative/path.json",
            "no-extension",
            ".",
            "..",
            "/",
        ],
    )
    def test_no_expansion_needed(self, path: str) -> None:
        assert expand_path(path) == path

    def test_empty_string(self) -> None:
        # Neither ``~`` nor ``$`` present → identity.
        assert expand_path("") == ""


# =============================================================================
# resolve_path
# =============================================================================


class TestResolvePathNone:
    def test_returns_none_for_none(self) -> None:
        assert resolve_path(None) is None


class TestResolvePathTypes:
    def test_returns_path_object(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        result = resolve_path("~/foo")
        assert isinstance(result, Path)

    def test_returns_absolute(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = resolve_path("relative/file.toml")
        assert result is not None
        assert result.is_absolute()


class TestResolvePathSemantics:
    def test_resolves_against_cwd(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = resolve_path("subdir/x.toml")
        # tmp_path may itself be a symlink (especially on macOS), so we
        # compare resolved-to-resolved instead of string-prefix.
        assert result is not None
        assert result == (tmp_path / "subdir" / "x.toml").resolve()

    def test_resolves_relative_dotdot(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        monkeypatch.chdir(deep)
        result = resolve_path("../../target.toml")
        assert result is not None
        assert result == (tmp_path / "target.toml").resolve()

    def test_resolves_tilde_via_expand_then_resolve(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        result = resolve_path("~/configs/app.toml")
        assert result is not None
        assert result == (tmp_path / "configs" / "app.toml").resolve()

    def test_empty_string_resolves_to_cwd(self, tmp_path, monkeypatch) -> None:
        """:func:`Path('').resolve()` returns the CWD. Documented as a
        consequence of the chained ``expand_path() → Path().resolve()``."""
        monkeypatch.chdir(tmp_path)
        result = resolve_path("")
        assert result == tmp_path.resolve()

    def test_resolves_missing_env_var_literal_path(self, tmp_path, monkeypatch) -> None:
        """A missing ``$VAR`` is left literal by expand_path; resolve_path
        then constructs a Path with the literal ``$VAR`` component in it.
        That's deterministic (no exception); we just verify no crash and
        the literal is preserved.
        """
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("CONFY_UNRESOLVED", raising=False)
        result = resolve_path("$CONFY_UNRESOLVED/file")
        assert result is not None
        # The literal '$CONFY_UNRESOLVED' should appear as a path component
        # since expand_path left it alone.
        assert "$CONFY_UNRESOLVED" in str(result)


# =============================================================================
# Smoke test of the documented examples in docstrings
# =============================================================================


class TestDocstringExamples:
    """Verify the examples in :func:`expand_path` and :func:`resolve_path`
    docstrings actually behave as advertised.
    """

    def test_expand_path_example_tilde(self, monkeypatch) -> None:
        monkeypatch.setenv("HOME", "/home/user")
        assert expand_path("~/configs/app.toml") == "/home/user/configs/app.toml"

    def test_expand_path_example_envvar(self, monkeypatch) -> None:
        # The docstring's example uses $HOME; mirror that.
        monkeypatch.setenv("HOME", "/home/user")
        assert expand_path("$HOME/.config/app.toml") == "/home/user/.config/app.toml"

    def test_expand_path_example_none(self) -> None:
        assert expand_path(None) is None
