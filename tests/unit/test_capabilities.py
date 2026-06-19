# tests/unit/test_capabilities.py
"""Unit tests for :mod:`confy.capabilities`."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from confy.capabilities import (
    CapabilityDescription,
    CapabilityExample,
    mcp_tool_to_capability,
    normalize_risk_level,
    render_for_llm,
)

pytestmark = pytest.mark.unit


def _capability(**overrides: object) -> CapabilityDescription:
    data = {
        "name": "read_file",
        "description": "Read a UTF-8 text file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        "output_schema": {"type": "string"},
        "examples": [
            CapabilityExample(
                description="Read config",
                input={"path": "~/.wairu/config.toml"},
                output="config text",
            ),
            CapabilityExample(description="Read notes", input={"path": "notes.md"}),
        ],
        "risk_level": "moderate",
        "guidance": "Use for local text files only.",
        "origin": "wairu.tools",
        "namespace": "filesystem",
        "version": "1.0.0",
        "tags": ["filesystem", "read"],
    }
    data.update(overrides)
    return CapabilityDescription(**data)  # type: ignore[arg-type]


class TestCapabilityDescription:
    def test_full_dataclass_serializes_with_asdict(self) -> None:
        capability = _capability()

        assert asdict(capability)["examples"][0]["input"] == {
            "path": "~/.wairu/config.toml"
        }
        assert capability.risk_level == "moderate"

    def test_minimum_fields_use_stable_defaults(self) -> None:
        capability = CapabilityDescription(name="noop", description="Do nothing.")

        assert capability.input_schema == {}
        assert capability.output_schema == {}
        assert capability.examples == []
        assert capability.risk_level == "safe"
        assert capability.origin == ""
        assert capability.namespace is None
        assert capability.tags == []


class TestRiskNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, "safe"),
            ("none", "safe"),
            ("low", "safe"),
            ("medium", "moderate"),
            ("moderate", "moderate"),
            ("high", "high"),
            ("restricted", "restricted"),
            ("critical", "restricted"),
        ],
    )
    def test_normalizes_local_risk_labels(self, raw: str | None, expected: str) -> None:
        assert normalize_risk_level(raw) == expected

    def test_unknown_risk_uses_default(self) -> None:
        assert normalize_risk_level("custom", default="moderate") == "moderate"


class TestRenderForLLM:
    def test_empty_capabilities_have_stable_empty_state(self) -> None:
        assert render_for_llm([]) == "AVAILABLE CAPABILITIES (0):\n- none"

    def test_compact_renders_one_line_per_capability(self) -> None:
        text = render_for_llm([
            _capability(name="read_file"),
            _capability(name="write_file", description="Write a text file."),
        ], style="compact")

        assert text.splitlines() == [
            "AVAILABLE CAPABILITIES (2):",
            "- read_file: Read a UTF-8 text file.",
            "- write_file: Write a text file.",
        ]

    def test_detailed_includes_risk_schemas_guidance_and_examples(self) -> None:
        text = render_for_llm([_capability()], style="detailed")

        assert "AVAILABLE CAPABILITIES:" in text
        assert "read_file - Read a UTF-8 text file." in text
        assert "  Origin: wairu.tools" in text
        assert "  Risk: moderate" in text
        assert "  Guidance: Use for local text files only." in text
        assert '"required": ["path"]' in text
        assert "  Outputs: {\"type\": \"string\"}" in text
        assert "    - Read config: {\"path\": \"~/.wairu/config.toml\"} -> \"config text\"" in text

    def test_grouped_renders_namespace_headers(self) -> None:
        text = render_for_llm(
            [
                _capability(name="read_file", namespace="filesystem"),
                _capability(name="http_get", namespace="network"),
            ],
            style="grouped",
        )

        assert "== filesystem ==" in text
        assert "== network ==" in text
        assert text.index("== filesystem ==") < text.index("== network ==")

    def test_example_limit_truncates_examples(self) -> None:
        text = render_for_llm([_capability()], example_limit=1)

        assert "Read config" in text
        assert "Read notes" not in text
        assert "... 1 more example(s)" in text

    def test_include_risk_false_omits_risk_lines(self) -> None:
        text = render_for_llm([_capability()], include_risk=False)

        assert "Risk:" not in text

    def test_include_schemas_false_omits_schema_lines(self) -> None:
        text = render_for_llm([_capability()], include_schemas=False)

        assert "Inputs:" not in text
        assert "Outputs:" not in text

    def test_invalid_style_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown capability render style"):
            render_for_llm([_capability()], style="unknown")  # type: ignore[arg-type]


class TestMCPAdapter:
    def test_mcp_tool_to_capability(self) -> None:
        capability = mcp_tool_to_capability(
            "filesystem",
            {
                "name": "read_file",
                "description": "Read a file.",
                "inputSchema": {"type": "object"},
            },
        )

        assert capability.name == "read_file"
        assert capability.description == "Read a file."
        assert capability.input_schema == {"type": "object"}
        assert capability.origin == "mcp.filesystem"
        assert capability.namespace == "filesystem"
