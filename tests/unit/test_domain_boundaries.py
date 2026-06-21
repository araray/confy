# tests/unit/test_domain_boundaries.py
"""Repository-boundary tests for confy.

Confy is a configuration library. LLM/model/tooling primitives belong in
llmcore, grimoire, semantiscan, or application adapters, not here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFY_PACKAGE = REPO_ROOT / "confy"

FORBIDDEN_DOMAIN_MODULES = {
    "tokens.py",
    "capabilities.py",
    "models.py",
    "agents.py",
    "tools.py",
}
FORBIDDEN_DEPENDENCY_PREFIXES = (
    "llmcore",
    "semantiscan",
    "grimoire",
    "wairu",
    "tiktoken",
)


def test_confy_has_no_llm_domain_modules() -> None:
    existing = {path.name for path in CONFY_PACKAGE.iterdir() if path.is_file()}

    assert existing.isdisjoint(FORBIDDEN_DOMAIN_MODULES)


def test_confy_has_no_llm_domain_dependencies() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    dependencies = list(project.get("dependencies", []))
    optional_dependencies = project.get("optional-dependencies", {})

    all_requirements = dependencies[:]
    for requirements in optional_dependencies.values():
        all_requirements.extend(requirements)

    normalized = [requirement.lower() for requirement in all_requirements]

    assert all(
        not requirement.startswith(FORBIDDEN_DEPENDENCY_PREFIXES)
        for requirement in normalized
    )
    assert "accurate-tokens" not in optional_dependencies
