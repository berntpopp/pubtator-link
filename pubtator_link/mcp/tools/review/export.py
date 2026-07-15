from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.mcp.annotations import FILE_EXPORT_ANNOTATIONS
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.tools import review as review_tools
from pubtator_link.mcp.tools.review._helpers import make_mcp_tool_for


def register_export_tools(mcp: FastMCP, profile: MCPToolProfile) -> None:
    mcp_tool_for = make_mcp_tool_for(mcp, profile)

    @mcp_tool_for(
        "full",
        name="export_review_audit_bundle",
        title="Export Review Audit Bundle",
        output_schema=None,
        annotations=FILE_EXPORT_ANNOTATIONS,
    )
    async def export_review_audit_bundle(
        review_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Review index to export the audit bundle for.",
                examples=["demo"],
            ),
        ],
        session_id: Annotated[
            str | None,
            Field(description="Optional staged session to scope the export to."),
        ] = None,
        save_to_file: Annotated[
            bool,
            Field(
                description="Write the bundle to the configured export directory instead of inline."
            ),
        ] = False,
        fallback_inline: Annotated[
            bool,
            Field(description="Return the bundle inline if file export is unavailable."),
        ] = False,
        response_mode: Annotated[
            Literal["full", "compact"],
            Field(description="Bundle verbosity: 'compact' (default) or 'full'."),
        ] = "compact",
    ) -> dict[str, Any]:
        """Use this when a user needs to export review preparation status, source coverage, resolver attempts, retrieval runs, passage IDs, and stable citation keys for scientific auditability."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_review_audit_service()
            return await review_tools.export_review_audit_bundle_impl(
                service=service,
                review_id=review_id,
                session_id=session_id,
                save_to_file=save_to_file,
                fallback_inline=fallback_inline,
                response_mode=response_mode,
            )

        return await run_mcp_tool("export_review_audit_bundle", call)
