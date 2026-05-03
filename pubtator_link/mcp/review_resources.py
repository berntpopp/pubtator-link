from __future__ import annotations

from typing import Any, cast

from fastmcp import FastMCP

from pubtator_link.mcp.profiles import MCPToolProfile, tool_names_for_profile
from pubtator_link.mcp.service_adapters import (
    review_audit_resource_impl,
    review_llm_context_resource_impl,
    review_passage_audit_resource_impl,
    review_passage_resource_impl,
    review_session_detail_resource_impl,
    review_sessions_resource_impl,
    review_summary_resource_impl,
)


async def get_review_summary_resource(*, service: Any, review_id: str) -> dict[str, Any]:
    return await review_summary_resource_impl(service=service, review_id=review_id)


async def get_review_sessions_resource(*, service: Any, review_id: str) -> dict[str, Any]:
    return await review_sessions_resource_impl(service=service, review_id=review_id)


async def get_review_session_detail_resource(
    *,
    service: Any,
    review_id: str,
    session_id: str,
) -> dict[str, Any]:
    return await review_session_detail_resource_impl(
        service=service,
        review_id=review_id,
        session_id=session_id,
    )


async def get_review_passage_resource(
    *,
    service: Any,
    review_id: str,
    passage_id: str,
) -> dict[str, Any]:
    return await review_passage_resource_impl(
        service=service,
        review_id=review_id,
        passage_id=passage_id,
    )


async def get_review_audit_resource(*, service: Any, review_id: str) -> dict[str, Any]:
    return await review_audit_resource_impl(service=service, review_id=review_id)


async def get_review_passage_audit_resource(
    *,
    service: Any,
    review_id: str,
    passage_id: str,
) -> dict[str, Any]:
    return await review_passage_audit_resource_impl(
        service=service,
        review_id=review_id,
        passage_id=passage_id,
    )


def get_review_llm_context_resource(
    *,
    review_id: str,
    latest: bool = False,
) -> dict[str, Any]:
    return review_llm_context_resource_impl(review_id=review_id, latest=latest)


def get_tool_detail_resource(tool_name: str) -> dict[str, Any]:
    tools = _runtime_tool_metadata()
    tool = tools.get(tool_name)
    if tool is None:
        return {"error": "not_found", "message": f"Unknown tool: {tool_name}"}

    return {
        "name": tool_name,
        "title": getattr(tool, "title", None),
        "description": getattr(tool, "description", None) or "",
        "profile_visibility": _profile_visibility(tool_name),
        "input_schema": getattr(tool, "parameters", None),
        "output_schema": getattr(tool, "output_schema", None)
        or getattr(getattr(tool, "fn_metadata", None), "output_schema", None),
    }


def _profile_visibility(tool_name: str) -> list[MCPToolProfile]:
    profiles: tuple[MCPToolProfile, ...] = ("lean", "full", "readonly")
    return [profile for profile in profiles if tool_name in tool_names_for_profile(profile)]


def _runtime_tool_metadata() -> dict[str, Any]:
    from pubtator_link.mcp.metadata import register_metadata
    from pubtator_link.mcp.tools.diagnostics import register_diagnostics_tools
    from pubtator_link.mcp.tools.discovery import register_discovery_tools
    from pubtator_link.mcp.tools.literature import register_literature_tools
    from pubtator_link.mcp.tools.publications import register_publication_tools
    from pubtator_link.mcp.tools.review import register_review_tools
    from pubtator_link.mcp.tools.text_annotations import register_text_annotation_tools

    mcp = FastMCP(name="pubtator-link-tool-metadata")
    register_metadata(mcp, profile="full")
    register_literature_tools(mcp, profile="full")
    register_discovery_tools(mcp, profile="full")
    register_diagnostics_tools(mcp, profile="full")
    register_publication_tools(mcp, profile="full")
    register_text_annotation_tools(mcp, profile="full")
    register_review_tools(mcp, profile="full")
    provider = cast(Any, mcp.providers[0])
    return {
        component.name: component
        for key, component in provider._components.items()
        if key.startswith("tool:")
    }
