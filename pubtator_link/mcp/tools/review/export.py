from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from pubtator_link.mcp.annotations import FILE_EXPORT_ANNOTATIONS
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.tools import review as review_tools
from pubtator_link.mcp.tools.review._helpers import make_mcp_tool_for
from pubtator_link.models.review_rerag import McpReviewAuditBundleResponse


def register_export_tools(mcp: FastMCP, profile: MCPToolProfile) -> None:
    mcp_tool_for = make_mcp_tool_for(mcp, profile)

    @mcp_tool_for(
        "full",
        name="pubtator_export_review_audit_bundle",
        title="Export Review Audit Bundle",
        output_schema=McpReviewAuditBundleResponse.model_json_schema(),
        annotations=FILE_EXPORT_ANNOTATIONS,
    )
    async def export_review_audit_bundle(
        review_id: str,
        session_id: str | None = None,
        export_path: str | None = None,
        fallback_inline: bool = False,
    ) -> dict[str, Any]:
        """Use this when a user needs to export review preparation status, source coverage, resolver attempts, retrieval runs, passage IDs, and stable citation keys for scientific auditability."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_review_audit_service()
            return await review_tools.export_review_audit_bundle_impl(
                service=service,
                review_id=review_id,
                session_id=session_id,
                export_path=export_path,
                fallback_inline=fallback_inline,
            )

        return await run_mcp_tool("pubtator_export_review_audit_bundle", call)
