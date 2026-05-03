from __future__ import annotations

from typing import Any, Protocol

from fastmcp import FastMCP

from pubtator_link.api.routes.dependencies import get_diagnostics_service
from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile, tool_names_for_profile
from pubtator_link.models.responses import DiagnosticsResponse


class DiagnosticsService(Protocol):
    async def get_diagnostics(self) -> DiagnosticsResponse: ...


def register_diagnostics_tools(mcp: FastMCP, profile: MCPToolProfile = "lean") -> None:
    @mcp.tool(
        name="pubtator.diagnostics",
        title="PubTator-Link Diagnostics",
        output_schema=DiagnosticsResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def diagnostics() -> dict[str, Any]:
        """Use this when a client needs PubTator-Link subsystem status and recovery commands."""
        service = await get_diagnostics_service()
        return await run_mcp_tool(
            "pubtator.diagnostics",
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
        grounded_review = workflow.get("grounded_review")
        allowed_tools = tool_names_for_profile(profile)
        if isinstance(grounded_review, list):
            workflow["grounded_review"] = [
                tool_name for tool_name in grounded_review if tool_name in allowed_tools
            ]
        one_call = workflow.get("one_call")
        if isinstance(one_call, str) and one_call not in allowed_tools:
            workflow.pop("one_call", None)
    return payload
