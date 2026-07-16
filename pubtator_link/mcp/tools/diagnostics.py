from __future__ import annotations

import re
from typing import Any, Protocol

from fastmcp import FastMCP

from pubtator_link.api.routes.dependencies import get_diagnostics_service
from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import (
    MCPToolProfile,
    reachable_tools,
    tool_names_for_profile,
)
from pubtator_link.models.responses import DiagnosticsResponse


class DiagnosticsService(Protocol):
    async def get_diagnostics(self) -> DiagnosticsResponse: ...


def _filter_diagnostic_protocol(
    profile: MCPToolProfile,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Sanitize only gateway-authored diagnostic recommendation fields.

    Recovery strings and historical-error fields are gateway diagnostic protocol
    and must not advertise tools missing from the profile.
    """
    unavailable = tool_names_for_profile("full") - tool_names_for_profile(profile)
    if not unavailable:
        return payload
    names = "|".join(re.escape(name) for name in sorted(unavailable, key=len, reverse=True))
    pattern = re.compile(rf"(?<![a-z0-9_])(?:{names})(?![a-z0-9_])")
    filtered = dict(payload)
    recovery = filtered.get("recovery")
    if isinstance(recovery, list):
        filtered["recovery"] = [
            pattern.sub("an unavailable tool", item) if isinstance(item, str) else item
            for item in recovery
        ]
    subsystems = filtered.get("subsystems")
    if not isinstance(subsystems, dict):
        return filtered
    recent_errors = subsystems.get("recent_mcp_errors")
    if not isinstance(recent_errors, dict):
        return filtered
    latest = recent_errors.get("latest")
    if not isinstance(latest, list):
        return filtered

    def filter_error(error: Any) -> Any:
        if not isinstance(error, dict):
            return error
        filtered_error = dict(error)
        if filtered_error.get("tool_name") in unavailable:
            filtered_error["tool_name"] = "unavailable_tool"
        message = filtered_error.get("message")
        if isinstance(message, str):
            filtered_error["message"] = pattern.sub("an unavailable tool", message)
        return filtered_error

    filtered_errors = dict(recent_errors)
    filtered_errors["latest"] = [filter_error(error) for error in latest]
    filtered_subsystems = dict(subsystems)
    filtered_subsystems["recent_mcp_errors"] = filtered_errors
    filtered["subsystems"] = filtered_subsystems
    return filtered


def register_diagnostics_tools(mcp: FastMCP, profile: MCPToolProfile = "lean") -> None:
    @mcp.tool(
        name="diagnostics",
        title="PubTator-Link Diagnostics",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"meta"},
    )
    async def diagnostics() -> dict[str, Any]:
        """Use this when a client needs PubTator-Link subsystem status and recovery commands."""
        service = await get_diagnostics_service()
        return await run_mcp_tool(
            "diagnostics",
            lambda: _diagnostics_impl(service, profile=profile),
        )


async def _diagnostics_impl(
    service: DiagnosticsService,
    *,
    profile: MCPToolProfile = "lean",
) -> dict[str, Any]:
    payload = (await service.get_diagnostics()).model_dump()
    workflow = payload.get("minimum_workflow")
    if isinstance(workflow, dict):
        if profile == "readonly":
            workflow["grounded_review"] = reachable_tools(
                profile,
                (
                    "search_literature",
                    "preflight_review_sources",
                    "get_publication_passages",
                ),
            )
            workflow.pop("one_call", None)
        else:
            grounded_review = workflow.get("grounded_review")
            allowed_tools = tool_names_for_profile(profile)
            if isinstance(grounded_review, list):
                workflow["grounded_review"] = [
                    tool_name for tool_name in grounded_review if tool_name in allowed_tools
                ]
            one_call = workflow.get("one_call")
            if isinstance(one_call, str) and one_call not in allowed_tools:
                workflow.pop("one_call", None)
    return _filter_diagnostic_protocol(profile, payload)
