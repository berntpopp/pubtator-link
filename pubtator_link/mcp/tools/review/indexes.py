from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp import Context, FastMCP
from pydantic import Field

from pubtator_link.mcp.annotations import IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS, READ_ONLY_OPEN_WORLD
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.tools import review as review_tools
from pubtator_link.mcp.tools.review._helpers import (
    _report_index_progress,
    _warn_if_degraded,
    make_mcp_tool_for,
)
from pubtator_link.models.review_rerag import (
    IndexReviewEvidenceResponse,
    InspectReviewIndexResponse,
    ListReviewIndexesResponse,
    ReviewIndexSummaryResponse,
    SampleSectionPolicy,
)


def register_indexes_tools(mcp: FastMCP, profile: MCPToolProfile) -> None:
    mcp_tool_for = make_mcp_tool_for(mcp, profile)

    @mcp_tool_for(
        "full",
        "readonly",
        name="list_review_indexes",
        title="List Review Indexes",
        output_schema=ListReviewIndexesResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def list_review_indexes(
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Use this when a user needs persisted review indexes with preparation status, source counts, passage counts, and approximate storage size."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_review_index_lifecycle_service()
            return await review_tools.list_review_indexes_impl(
                service=service, limit=limit, offset=offset
            )

        return await run_mcp_tool("list_review_indexes", call)

    @mcp_tool_for(
        "full",
        "readonly",
        name="get_review_index_summary",
        title="Get Review Index Summary",
        output_schema=ReviewIndexSummaryResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_review_index_summary(review_id: str) -> dict[str, Any]:
        """Use this when a user needs one persisted review index summary without loading passage samples."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_review_index_lifecycle_service()
            return await review_tools.get_review_index_summary_impl(
                service=service, review_id=review_id
            )

        return await run_mcp_tool("get_review_index_summary", call)

    @mcp_tool_for(
        "lean",
        "full",
        name="index_review_evidence",
        title="Index Review Evidence",
        output_schema=IndexReviewEvidenceResponse.model_json_schema(),
        annotations=IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
        exclude_args=["prepare_mode"],
    )
    async def index_review_evidence(
        review_id: Annotated[str, Field(min_length=1)],
        pmids: list[str] | None = None,
        curated_urls: list[str] | None = None,
        session_id: str | None = None,
        prepare_mode: Literal["selected"] = "selected",
        wait_for_status: Literal["complete", "complete_or_partial", "terminal"] | None = None,
        wait_until_ready: bool = False,
        timeout_ms: int = 0,
        dry_run: bool = False,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Use this when a review needs review-scoped evidence preparation for a review_id and PMIDs/curated URLs. Call this before get_review_context_batch, use session_id to scope staged research sessions, set wait_until_ready for small corpora, and inspect preparation_status before retrieval."""

        async def call() -> dict[str, Any]:
            queue = await review_tools.get_review_queue()
            if wait_until_ready:
                await _report_index_progress(ctx, progress=0)
            result = await review_tools.index_review_evidence_impl(
                queue=queue,
                review_id=review_id,
                pmids=pmids,
                curated_urls=curated_urls,
                prepare_mode=prepare_mode,
                session_id=session_id,
                wait_for_completion=wait_until_ready,
                wait_for_status="complete_or_partial" if wait_until_ready else wait_for_status,
                timeout_ms=timeout_ms,
                dry_run=dry_run,
            )
            if wait_until_ready:
                status = result.get("preparation_status", {})
                complete = int(status.get("complete", 0)) + int(status.get("partial", 0))
                total = max(
                    1,
                    int(status.get("queued", 0))
                    + int(status.get("running", 0))
                    + complete
                    + int(status.get("failed", 0)),
                )
                progress = (
                    100 if result.get("timed_out") is False else min(95, (complete / total) * 100)
                )
                await _report_index_progress(ctx, progress=progress)
            await _warn_if_degraded(ctx, result)
            return result

        return await run_mcp_tool(
            "index_review_evidence",
            call,
            pmids=pmids or [],
        )

    @mcp_tool_for(
        "lean",
        "full",
        "readonly",
        name="inspect_review_index",
        title="Inspect Review Index",
        output_schema=InspectReviewIndexResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def inspect_review_index(
        review_id: str,
        session_id: str | None = None,
        pmids: list[str] | None = None,
        include_passage_samples: bool = False,
        sample_per_pmid: int = 2,
        min_sample_chars: int = 80,
        sample_section_policy: SampleSectionPolicy = "evidence_first",
        include_metadata: bool = False,
        metadata: Literal["basic", "full"] = "basic",
        response_mode: Literal["compact", "full"] = "compact",
        limit: Annotated[int | None, Field(ge=1, le=100)] = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Use this when a user needs to inspect indexed PMIDs, sections, passage counts, and failures for a review_id, including source coverage."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_review_context_service()
            return await review_tools.inspect_review_index_impl(
                service=service,
                review_id=review_id,
                session_id=session_id,
                pmids=pmids,
                include_passage_samples=include_passage_samples,
                sample_per_pmid=sample_per_pmid,
                min_sample_chars=min_sample_chars,
                sample_section_policy=sample_section_policy,
                include_metadata=include_metadata,
                metadata=metadata,
                response_mode=response_mode,
                limit=limit,
                cursor=cursor,
            )

        return await run_mcp_tool("inspect_review_index", call, pmids=pmids)
