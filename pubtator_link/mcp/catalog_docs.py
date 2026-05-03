from __future__ import annotations

from pubtator_link.mcp.catalog import ToolCatalogEntry, build_tool_catalog
from pubtator_link.mcp.facade import create_pubtator_mcp
from pubtator_link.mcp.profiles import MCPToolProfile

PROFILES: tuple[MCPToolProfile, ...] = ("lean", "full", "readonly")


def _format_tuple(values: tuple[str, ...]) -> str:
    if not values:
        return "None"
    return ", ".join(f"`{value}`" for value in values)


def _format_output_schema(entry: ToolCatalogEntry) -> str:
    schema_name = entry.output_schema_name or "None"
    availability = "yes" if entry.has_output_schema else "no"
    return f"`{schema_name}`; has_output_schema: `{availability}`"


def _format_next_tools_by_profile(
    tool_name: str,
    catalogs_by_profile: dict[MCPToolProfile, dict[str, ToolCatalogEntry]],
) -> str:
    segments: list[str] = []
    for profile in PROFILES:
        catalog = catalogs_by_profile[profile]
        if tool_name in catalog:
            segments.append(f"{profile}: {_format_tuple(catalog[tool_name].next_tools)}")
    return "; ".join(segments) if segments else "None"


def render_tool_catalog_markdown() -> str:
    catalogs_by_profile = {
        profile: build_tool_catalog(create_pubtator_mcp(profile=profile), profile=profile)
        for profile in PROFILES
    }
    catalog = catalogs_by_profile["full"]
    lines = [
        "# MCP Tool Catalog",
        "",
        "Generated from the runtime FastMCP tool registry plus catalog-only supplements.",
        "Do not edit by hand; run `uv run python scripts/generate_mcp_tool_catalog.py`.",
        "",
    ]
    for name, entry in sorted(catalog.items()):
        lines.extend(
            [
                f"## `{name}`",
                "",
                f"- Name: `{entry.name}`",
                f"- Title: {entry.title}",
                f"- Category: `{entry.category}`",
                f"- Profiles: {_format_tuple(entry.profiles)}",
                f"- Stability: `{entry.stability}`",
                f"- Description: {entry.description}",
                f"- Do not use for: {_format_tuple(entry.do_not_use_for)}",
                f"- Example: `{entry.example}`",
                f"- Next tools by profile: {_format_next_tools_by_profile(name, catalogs_by_profile)}",
                f"- Resource links: {_format_tuple(entry.resource_links)}",
                f"- Output schema: {_format_output_schema(entry)}",
                "",
            ]
        )
    return "\n".join(lines)
