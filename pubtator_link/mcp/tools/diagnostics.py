from __future__ import annotations

from typing import Any, Protocol

from fastmcp import FastMCP

from pubtator_link.api.routes.dependencies import get_diagnostics_service
from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
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
        """Use this to check PubTator-Link subsystem status and recovery commands."""
        service = await get_diagnostics_service()
        return await run_mcp_tool(
            "pubtator.diagnostics",
            lambda: _diagnostics_impl(service),
        )


async def _diagnostics_impl(service: DiagnosticsService) -> dict[str, Any]:
    return (await service.get_diagnostics()).model_dump()
