"""Shared capability descriptions for LLM-facing tool guidance.

This module defines the ecosystem's neutral shape for describing tools,
runes, commands, and remote capabilities to language models. Consumer
projects keep their native tool models and adapt to this type only at the
prompt boundary.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

RiskLevel = Literal["safe", "moderate", "high", "restricted"]
RenderStyle = Literal["compact", "detailed", "grouped"]

_RISK_ALIASES: dict[str, RiskLevel] = {
    "": "safe",
    "none": "safe",
    "no": "safe",
    "low": "safe",
    "safe": "safe",
    "medium": "moderate",
    "moderate": "moderate",
    "elevated": "moderate",
    "high": "high",
    "restricted": "restricted",
    "critical": "restricted",
    "dangerous": "restricted",
}


@dataclass
class CapabilityExample:
    """Concrete invocation example for a capability."""

    description: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    output: Any | None = None


@dataclass
class CapabilityDescription:
    """Canonical LLM-facing description of a tool, rune, or command."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    examples: list[CapabilityExample] = field(default_factory=list)
    risk_level: RiskLevel = "safe"
    guidance: str = ""
    origin: str = ""
    namespace: str | None = None
    version: str | None = None
    tags: list[str] = field(default_factory=list)


def normalize_risk_level(value: str | None, *, default: RiskLevel = "safe") -> RiskLevel:
    """Normalize local risk labels into the shared risk vocabulary.

    Existing projects use labels such as ``low``/``medium``/``none`` while
    the shared capability type uses ``safe``/``moderate``/``high``/
    ``restricted``. Unknown values fall back to ``default`` so adapters do
    not fail on non-critical metadata drift.
    """

    if value is None:
        return default
    return _RISK_ALIASES.get(str(value).strip().lower(), default)


def render_for_llm(
    capabilities: list[CapabilityDescription],
    *,
    style: RenderStyle = "detailed",
    include_risk: bool = True,
    include_examples: bool = True,
    example_limit: int | None = 2,
    include_schemas: bool = True,
) -> str:
    """Render capabilities as stable prompt text for an LLM."""

    if style == "compact":
        rendered = _render_compact(capabilities)
    elif style == "detailed":
        rendered = _render_detailed(
            capabilities,
            include_header=True,
            include_risk=include_risk,
            include_examples=include_examples,
            example_limit=example_limit,
            include_schemas=include_schemas,
        )
    elif style == "grouped":
        rendered = _render_grouped(
            capabilities,
            include_risk=include_risk,
            include_examples=include_examples,
            example_limit=example_limit,
            include_schemas=include_schemas,
        )
    else:
        raise ValueError(f"Unknown capability render style: {style}")

    if len(rendered) > 10_000:
        logger.warning(
            "Rendered capability guidance is %s characters; consider compact style",
            len(rendered),
        )
    return rendered


def mcp_tool_to_capability(
    server_name: str,
    mcp_tool: dict[str, Any],
) -> CapabilityDescription:
    """Convert an MCP tool dictionary into a shared capability."""

    return CapabilityDescription(
        name=str(mcp_tool.get("name", "")),
        description=str(mcp_tool.get("description", "")),
        input_schema=dict(mcp_tool.get("inputSchema") or {}),
        origin=f"mcp.{server_name}",
        namespace=server_name,
    )


def _render_compact(capabilities: list[CapabilityDescription]) -> str:
    lines = [f"AVAILABLE CAPABILITIES ({len(capabilities)}):"]
    if not capabilities:
        lines.append("- none")
        return "\n".join(lines)

    for capability in capabilities:
        lines.append(f"- {capability.name}: {capability.description}")
    return "\n".join(lines)


def _render_grouped(
    capabilities: list[CapabilityDescription],
    *,
    include_risk: bool,
    include_examples: bool,
    example_limit: int | None,
    include_schemas: bool,
) -> str:
    if not capabilities:
        return _render_compact([])

    groups: OrderedDict[str, list[CapabilityDescription]] = OrderedDict()
    for capability in capabilities:
        namespace = capability.namespace or "ungrouped"
        groups.setdefault(namespace, []).append(capability)

    parts = ["AVAILABLE CAPABILITIES:"]
    for namespace, group in groups.items():
        parts.append(f"\n== {namespace} ==")
        parts.append(
            _render_detailed(
                group,
                include_header=False,
                include_risk=include_risk,
                include_examples=include_examples,
                example_limit=example_limit,
                include_schemas=include_schemas,
            )
        )
    return "\n".join(parts)


def _render_detailed(
    capabilities: list[CapabilityDescription],
    *,
    include_header: bool,
    include_risk: bool,
    include_examples: bool,
    example_limit: int | None,
    include_schemas: bool,
) -> str:
    if not capabilities:
        return _render_compact([])

    parts: list[str] = []
    if include_header:
        parts.append("AVAILABLE CAPABILITIES:")

    for capability in capabilities:
        lines = [f"{capability.name} - {capability.description}"]
        if capability.origin:
            lines.append(f"  Origin: {capability.origin}")
        if include_risk:
            lines.append(f"  Risk: {capability.risk_level}")
        if capability.guidance:
            lines.append(f"  Guidance: {capability.guidance}")
        if include_schemas:
            lines.append(f"  Inputs: {_format_json(capability.input_schema)}")
            if capability.output_schema:
                lines.append(f"  Outputs: {_format_json(capability.output_schema)}")
        if include_examples and capability.examples:
            lines.extend(_render_examples(capability.examples, example_limit))
        parts.append("\n".join(lines))

    separator = "\n\n" if include_header else "\n"
    return separator.join(parts)


def _render_examples(examples: list[CapabilityExample], limit: int | None) -> list[str]:
    shown = examples if limit is None else examples[: max(limit, 0)]
    lines = ["  Examples:"]
    for example in shown:
        line = "    - "
        if example.description:
            line += example.description
            if example.input:
                line += f": {_format_json(example.input)}"
        else:
            line += _format_json(example.input)
        if example.output is not None:
            line += f" -> {_format_json(example.output)}"
        lines.append(line)

    if limit is not None and len(examples) > limit:
        lines.append(f"    ... {len(examples) - limit} more example(s)")
    return lines


def _format_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=True)


__all__ = [
    "CapabilityDescription",
    "CapabilityExample",
    "RenderStyle",
    "RiskLevel",
    "mcp_tool_to_capability",
    "normalize_risk_level",
    "render_for_llm",
]
