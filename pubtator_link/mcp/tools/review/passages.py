from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.tools import review as review_tools
from pubtator_link.mcp.tools.review._helpers import make_mcp_tool_for
from pubtator_link.models.review_rerag import ReviewAuditTrailResponse, ReviewPassageLookupResponse


def register_passages_tools(mcp: FastMCP, profile: MCPToolProfile) -> None:
    mcp_tool_for = make_mcp_tool_for(mcp, profile)

    @mcp_tool_for(
        "full",
        "readonly",
        name="pubtator_get_review_passages_by_id",
        title="Get Review Passages By ID",
        output_schema=ReviewPassageLookupResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_review_passages_by_id(
        review_id: str,
        passage_ids: list[str],
        session_id: str | None = None,
        max_chars_per_passage: int = 2200,
    ) -> dict[str, Any]:
        """Use this when a user needs exact prepared review passages by stable passage IDs from prior context packs or audit bundles. This only reads the review index and does not call upstream APIs."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_review_context_service()
            return await review_tools.get_review_passages_by_id_impl(
                service=service,
                review_id=review_id,
                passage_ids=passage_ids,
                session_id=session_id,
                max_chars_per_passage=max_chars_per_passage,
            )

        return await run_mcp_tool("pubtator_get_review_passages_by_id", call)

    @mcp_tool_for(
        "lean",
        "full",
        "readonly",
        name="pubtator_get_review_audit_trail",
        title="Get Review Audit Trail",
        output_schema=ReviewAuditTrailResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_review_audit_trail(
        review_id: str,
        passage_ids: list[str],
        session_id: str | None = None,
        max_chars_per_passage: int = 500,
    ) -> dict[str, Any]:
        """Use this when a user needs a copy-ready audit block for selected prepared review passage IDs without calling upstream APIs."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_review_context_service()
            return await review_tools.get_review_audit_trail_impl(
                service=service,
                review_id=review_id,
                passage_ids=passage_ids,
                session_id=session_id,
                max_chars_per_passage=max_chars_per_passage,
            )

        return await run_mcp_tool("pubtator_get_review_audit_trail", call)

    @mcp_tool_for(
        "full",
        "readonly",
        name="pubtator_get_neighboring_review_passages",
        title="Get Neighboring Review Passages",
        output_schema=ReviewPassageLookupResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_neighboring_review_passages(
        review_id: str,
        passage_id: str,
        session_id: str | None = None,
        before: int = 1,
        after: int = 1,
        same_section: bool = True,
        max_chars_per_passage: int = 2200,
    ) -> dict[str, Any]:
        """Use this when a user needs prepared review passages near a cited stable passage ID for local context expansion. This only reads the review index and does not call upstream APIs."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_review_context_service()
            return await review_tools.get_neighboring_review_passages_impl(
                service=service,
                review_id=review_id,
                passage_id=passage_id,
                session_id=session_id,
                before=before,
                after=after,
                same_section=same_section,
                max_chars_per_passage=max_chars_per_passage,
            )

        return await run_mcp_tool("pubtator_get_neighboring_review_passages", call)
