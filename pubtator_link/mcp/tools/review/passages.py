from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.tools import review as review_tools
from pubtator_link.mcp.tools.review._helpers import make_mcp_tool_for


def register_passages_tools(mcp: FastMCP, profile: MCPToolProfile) -> None:
    mcp_tool_for = make_mcp_tool_for(mcp, profile)

    @mcp_tool_for(
        "full",
        "readonly",
        name="get_review_passages_by_id",
        title="Get Review Passages By ID",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_review_passages_by_id(
        review_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Review index the passages belong to.",
                examples=["demo"],
            ),
        ],
        passage_ids: Annotated[
            list[str],
            Field(
                min_length=1,
                description="Stable prepared passage IDs to fetch verbatim.",
                examples=[["p1", "p2"]],
            ),
        ],
        session_id: Annotated[
            str | None,
            Field(description="Optional staged session to scope the lookup to."),
        ] = None,
        max_chars_per_passage: Annotated[
            int,
            Field(ge=100, le=20000, description="Character cap per returned passage."),
        ] = 2200,
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

        return await run_mcp_tool("get_review_passages_by_id", call)

    @mcp_tool_for(
        "lean",
        "full",
        "readonly",
        name="get_review_audit_trail",
        title="Get Review Audit Trail",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_review_audit_trail(
        review_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Review index to build the audit block for.",
                examples=["demo"],
            ),
        ],
        passage_ids: Annotated[
            list[str] | None,
            Field(
                description="Specific prepared passage IDs to audit; omit for the latest recorded set.",
                examples=[["p1"]],
            ),
        ] = None,
        session_id: Annotated[
            str | None,
            Field(description="Optional staged session to scope the audit to."),
        ] = None,
        max_chars_per_passage: Annotated[
            int,
            Field(ge=100, le=20000, description="Character cap per audited passage."),
        ] = 500,
    ) -> dict[str, Any]:
        """Use this when a user needs a copy-ready audit block for selected prepared review passage IDs or the latest recorded audit passages without calling upstream APIs."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_review_context_service()
            return await review_tools.get_review_audit_trail_impl(
                service=service,
                review_id=review_id,
                passage_ids=passage_ids,
                session_id=session_id,
                max_chars_per_passage=max_chars_per_passage,
            )

        return await run_mcp_tool("get_review_audit_trail", call)

    @mcp_tool_for(
        "full",
        "readonly",
        name="get_neighboring_review_passages",
        title="Get Neighboring Review Passages",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_neighboring_review_passages(
        review_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Review index the passage belongs to.",
                examples=["demo"],
            ),
        ],
        passage_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Anchor passage ID to expand context around.",
                examples=["p1"],
            ),
        ],
        session_id: Annotated[
            str | None,
            Field(description="Optional staged session to scope the lookup to."),
        ] = None,
        before: Annotated[
            int,
            Field(ge=0, le=20, description="Neighboring passages to include before the anchor."),
        ] = 1,
        after: Annotated[
            int,
            Field(ge=0, le=20, description="Neighboring passages to include after the anchor."),
        ] = 1,
        same_section: Annotated[
            bool,
            Field(description="Restrict neighbors to the anchor's section."),
        ] = True,
        max_chars_per_passage: Annotated[
            int,
            Field(ge=100, le=20000, description="Character cap per returned passage."),
        ] = 2200,
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

        return await run_mcp_tool("get_neighboring_review_passages", call)
