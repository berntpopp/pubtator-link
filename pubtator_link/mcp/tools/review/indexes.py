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
from pubtator_link.models.review_rerag import SampleSectionPolicy


def register_indexes_tools(mcp: FastMCP, profile: MCPToolProfile) -> None:
    mcp_tool_for = make_mcp_tool_for(mcp, profile)

    @mcp_tool_for(
        "full",
        "readonly",
        name="list_review_indexes",
        title="List Review Indexes",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def list_review_indexes(
        limit: Annotated[
            int,
            Field(ge=1, le=200, description="Maximum review indexes to return."),
        ] = 50,
        offset: Annotated[
            int,
            Field(ge=0, description="Zero-based row offset for pagination."),
        ] = 0,
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
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_review_index_summary(
        review_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Identifier of the persisted review index to summarize.",
                examples=["demo"],
            ),
        ],
    ) -> dict[str, Any]:
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
        output_schema=None,
        annotations=IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
        exclude_args=["prepare_mode"],
    )
    async def index_review_evidence(
        review_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Review index to prepare evidence into (created if absent).",
                examples=["demo"],
            ),
        ],
        pmids: Annotated[
            list[str] | None,
            Field(
                description="PubMed IDs to index as review evidence.",
                examples=[["12345"]],
            ),
        ] = None,
        curated_urls: Annotated[
            list[str] | None,
            Field(
                description="Curated full-text URLs (from the configured allowlist) to index.",
                examples=[["https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5334499/"]],
            ),
        ] = None,
        session_id: Annotated[
            str | None,
            Field(description="Optional staged research session to scope this preparation to."),
        ] = None,
        prepare_mode: Literal["selected"] = "selected",
        wait_for_status: Annotated[
            Literal["complete", "complete_or_partial", "terminal"] | None,
            Field(description="Block until this preparation status is reached, then return."),
        ] = None,
        wait_until_ready: Annotated[
            bool,
            Field(description="Block for small corpora until preparation completes or times out."),
        ] = False,
        timeout_ms: Annotated[
            int,
            Field(ge=0, le=600_000, description="Wait budget in milliseconds (0 = do not block)."),
        ] = 0,
        dry_run: Annotated[
            bool,
            Field(description="Plan the preparation and report counts without indexing."),
        ] = False,
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
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def inspect_review_index(
        review_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Review index to inspect.",
                examples=["demo"],
            ),
        ],
        session_id: Annotated[
            str | None,
            Field(description="Optional staged session to scope the inspection to."),
        ] = None,
        pmids: Annotated[
            list[str] | None,
            Field(
                description="Restrict the inspection to these indexed PMIDs.",
                examples=[["12345"]],
            ),
        ] = None,
        include_passage_samples: Annotated[
            bool,
            Field(description="Include a few sample passages per PMID."),
        ] = False,
        sample_per_pmid: Annotated[
            int,
            Field(ge=0, le=20, description="Sample passages to include per PMID."),
        ] = 2,
        min_sample_chars: Annotated[
            int,
            Field(ge=0, le=5000, description="Minimum characters for a sampled passage."),
        ] = 80,
        sample_section_policy: Annotated[
            SampleSectionPolicy,
            Field(description="Sampling order: 'evidence_first' (default) or 'original_order'."),
        ] = "evidence_first",
        include_metadata: Annotated[
            bool,
            Field(description="Include per-PMID citation metadata."),
        ] = False,
        metadata: Annotated[
            Literal["basic", "full"],
            Field(description="Metadata depth when included: 'basic' (default) or 'full'."),
        ] = "basic",
        response_mode: Annotated[
            Literal["compact", "full"],
            Field(description="Payload verbosity: 'compact' (default) or 'full'."),
        ] = "compact",
        limit: Annotated[
            int | None,
            Field(ge=1, le=100, description="Maximum indexed PMIDs to page over."),
        ] = 50,
        cursor: Annotated[
            str | None,
            Field(description="Opaque pagination cursor from a prior page."),
        ] = None,
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
