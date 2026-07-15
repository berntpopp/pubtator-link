from __future__ import annotations

from typing import Annotated, Any, cast

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.mcp.annotations import (
    IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    READ_ONLY_OPEN_WORLD,
)
from pubtator_link.mcp.argument_aliases import coalesce_query, merge_pmids
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.meta_budget import strip_meta_for_repeated_call
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.tools import review as review_tools
from pubtator_link.mcp.tools._vocab import PublicationType
from pubtator_link.mcp.tools.review._helpers import make_mcp_tool_for
from pubtator_link.models.review_rerag import (
    MaxResponseChars,
    ReviewResponseVerbosity,
)


def register_research_tools(mcp: FastMCP, profile: MCPToolProfile) -> None:
    mcp_tool_for = make_mcp_tool_for(mcp, profile)

    @mcp_tool_for(
        "lean",
        "full",
        "readonly",
        name="preflight_review_sources",
        title="Preflight Review Sources",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def preflight_review_sources(
        pmids: Annotated[
            list[str],
            Field(
                min_length=1,
                description="PubMed IDs to check source coverage and full-text availability for.",
                examples=[["25741868"]],
            ),
        ],
        pmid: Annotated[
            str | None,
            Field(min_length=1, description="Single-PMID convenience alias, merged with `pmids`."),
        ] = None,
    ) -> dict[str, Any]:
        """Use this when a user needs PMID source coverage, PMC fallback availability, and likely full-text versus abstract-only retrieval before indexing review evidence."""

        async def call() -> dict[str, Any]:
            selected_pmids = merge_pmids(pmids, pmid)
            service = await review_tools.get_source_preflight_service()
            return await review_tools.preflight_review_sources_impl(
                service=service,
                pmids=selected_pmids,
            )

        try:
            tool_pmids = merge_pmids(pmids, pmid)
        except ValueError:
            tool_pmids = None
        return await run_mcp_tool(
            "preflight_review_sources",
            call,
            pmids=tool_pmids,
            fallback_tool="get_publication_passages" if tool_pmids else None,
            fallback_args={"pmids": tool_pmids, "mode": "full_abstract"} if tool_pmids else None,
        )

    @mcp_tool_for(
        "full",
        name="stage_research_session",
        title="Stage Research Session",
        output_schema=None,
        annotations=NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    )
    async def stage_research_session(
        review_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Review index the staged session belongs to.",
                examples=["demo"],
            ),
        ],
        query: Annotated[
            str | None,
            Field(min_length=1, description="Search query used to stage candidate PMIDs."),
        ] = None,
        pmids: Annotated[
            list[str] | None,
            Field(description="Explicit candidate PMIDs to stage.", examples=[["12345"]]),
        ] = None,
        session_id: Annotated[
            str | None,
            Field(min_length=1, description="Reuse/extend an existing staged session."),
        ] = None,
        page: Annotated[
            int, Field(ge=1, le=1000, description="1-based search page to stage from.")
        ] = 1,
        sort: Annotated[
            str | None, Field(description="Search sort order (see search_literature.sort).")
        ] = None,
        filters: Annotated[
            str | None, Field(description="Advanced PubTator3 filter JSON string.")
        ] = None,
        publication_types: Annotated[
            list[PublicationType] | None,
            Field(
                description="Restrict staged candidates to these PubMed publication types.",
                examples=[["Review"]],
            ),
        ] = None,
        year_min: Annotated[
            int | None, Field(ge=1800, le=2030, description="Earliest publication year, inclusive.")
        ] = None,
        year_max: Annotated[
            int | None, Field(ge=1800, le=2030, description="Latest publication year, inclusive.")
        ] = None,
        sections: Annotated[
            list[str] | None,
            Field(
                description="Restrict the search to these article sections.",
                examples=[["title", "abstract"]],
            ),
        ] = None,
        max_candidates: Annotated[
            int, Field(ge=1, le=100, description="Maximum candidate PMIDs to stage.")
        ] = 20,
        stage_full_text: Annotated[
            bool, Field(description="Queue full-text preparation for staged candidates.")
        ] = True,
        include_meta: Annotated[
            bool, Field(description="Include the _meta orientation block.")
        ] = True,
    ) -> dict[str, Any]:
        """Use this when a user needs to stage candidate PMIDs with coverage hints and queued review preparation after search planning."""

        async def call() -> dict[str, Any]:
            selected_pmids = merge_pmids(pmids, None, max_items=100) if pmids else None
            service = await review_tools.get_research_session_service()
            return await review_tools.stage_research_session_impl(
                service=service,
                review_id=review_id,
                query=query,
                pmids=selected_pmids,
                session_id=session_id,
                page=page,
                sort=sort,
                filters=filters,
                publication_types=cast("list[str] | None", publication_types),
                year_min=year_min,
                year_max=year_max,
                sections=sections,
                max_candidates=max_candidates,
                stage_full_text=stage_full_text,
            )

        try:
            tool_pmids = merge_pmids(pmids, None, max_items=100)
        except ValueError:
            tool_pmids = None
        result = await run_mcp_tool(
            "stage_research_session",
            call,
            pmids=tool_pmids or [],
        )
        return result if include_meta else strip_meta_for_repeated_call(result)

    @mcp_tool_for(
        "lean",
        "full",
        name="ground_question",
        title="Ground Question",
        output_schema=None,
        annotations=IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    )
    async def ground_question(
        question: Annotated[
            str,
            Field(
                min_length=1,
                description="Research question to ground in citable literature evidence.",
                examples=["Does colchicine prevent FMF flares?"],
            ),
        ],
        max_pmids: Annotated[
            int, Field(ge=1, le=20, description="Maximum PMIDs to search and index.")
        ] = 8,
        max_results: Annotated[
            int | None,
            Field(ge=1, le=20, description="Alias for `max_pmids`; takes precedence when set."),
        ] = None,
        review_id: Annotated[
            str | None,
            Field(min_length=1, description="Review index to store/reuse evidence in."),
        ] = None,
        entity_ids: Annotated[
            list[str] | None,
            Field(
                description="PubTator entity IDs to anchor the search on.",
                examples=[["@GENE_MEFV"]],
            ),
        ] = None,
        guideline_boost: Annotated[
            bool, Field(description="Boost guideline / review articles during the search.")
        ] = True,
        wait_until_ready: Annotated[
            bool, Field(description="Block until preparation completes or times out.")
        ] = True,
        timeout_ms: Annotated[
            int, Field(ge=0, le=120_000, description="Preparation wait budget in milliseconds.")
        ] = 30_000,
        verbosity: Annotated[
            ReviewResponseVerbosity,
            Field(description="Field verbosity: 'lean' (default), 'standard', or 'full'."),
        ] = "lean",
        max_response_chars: Annotated[
            MaxResponseChars,
            Field(description="Response character budget: 'auto' (default) or an integer cap."),
        ] = "auto",
    ) -> dict[str, Any]:
        """Use this when a user wants one compact grounded evidence workflow from a question: search literature, index candidate PMIDs, inspect readiness, and retrieve citable review context."""

        async def call() -> dict[str, Any]:
            selected_question = question
            client = await review_tools.get_api_client()
            queue = await review_tools.get_review_queue()
            context_service = await review_tools.get_review_context_service()
            return await review_tools.ground_question_impl(
                client=client,
                queue=queue,
                context_service=context_service,
                question=selected_question,
                max_pmids=max_results or max_pmids,
                review_id=review_id,
                entity_ids=entity_ids,
                guideline_boost=guideline_boost,
                wait_until_ready=wait_until_ready,
                timeout_ms=timeout_ms,
                verbosity=verbosity,
                max_response_chars=max_response_chars,
            )

        return await run_mcp_tool("ground_question", call)

    @mcp_tool_for(
        "full",
        name="review_quickstart",
        title="Review Quickstart",
        output_schema=None,
        annotations=NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
        tags={"meta"},
    )
    async def review_quickstart(
        topic: Annotated[
            str | None,
            Field(
                min_length=1,
                description="Topic to spin up a casual review for. Provide one of topic, query, or question.",
                examples=["EGFR resistance in lung cancer"],
            ),
        ] = None,
        query: Annotated[str | None, Field(min_length=1, description="Alias for `topic`.")] = None,
        question: Annotated[
            str | None, Field(min_length=1, description="Alias for `topic`.")
        ] = None,
        n_pmids: Annotated[
            int, Field(ge=1, le=20, description="Number of PMIDs to stage/index.")
        ] = 8,
        review_id: Annotated[
            str | None, Field(min_length=1, description="Reuse an existing review index.")
        ] = None,
        session_id: Annotated[
            str | None, Field(min_length=1, description="Reuse an existing staged session.")
        ] = None,
        wait_until_ready: Annotated[
            bool, Field(description="Block until preparation completes or times out.")
        ] = False,
        timeout_ms: Annotated[
            int, Field(ge=0, le=120_000, description="Preparation wait budget in milliseconds.")
        ] = 0,
    ) -> dict[str, Any]:
        """Use this when a user wants one-shot casual review setup: search topic, stage/index up to n_pmids, inspect coverage, and return review_id/session_id for get_review_context_batch. Provide one of topic, query, or question."""

        async def call() -> dict[str, Any]:
            selected_topic = coalesce_query(topic, query, question)
            stage_service = await review_tools.get_research_session_service()
            context_service = await review_tools.get_review_context_service()
            return await review_tools.review_quickstart_impl(
                stage_service=stage_service,
                context_service=context_service,
                topic=selected_topic,
                n_pmids=n_pmids,
                review_id=review_id,
                session_id=session_id,
                wait_until_ready=wait_until_ready,
                timeout_ms=timeout_ms,
            )

        return await run_mcp_tool("review_quickstart", call)

    @mcp_tool_for(
        "full",
        "readonly",
        name="get_research_session_status",
        title="Get Research Session Status",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_research_session_status(
        session_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Staged research session to report status for.",
                examples=["session-1"],
            ),
        ],
        review_id: Annotated[
            str | None,
            Field(min_length=1, description="Optional review index the session belongs to."),
        ] = None,
    ) -> dict[str, Any]:
        """Use this when a user needs staged candidate, coverage, and preparation status for a research session."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_research_session_service()
            return await review_tools.get_research_session_status_impl(
                service=service,
                review_id=review_id,
                session_id=session_id,
            )

        return await run_mcp_tool("get_research_session_status", call)

    @mcp_tool_for(
        "full",
        "readonly",
        name="list_research_sessions",
        title="List Research Sessions",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def list_research_sessions(
        review_id: Annotated[
            str | None,
            Field(
                min_length=1,
                description="Optional review index to list sessions for; omit for recent global sessions.",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Use this when a user needs staged research sessions for orientation or one review ID."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_research_session_service()
            return await review_tools.list_research_sessions_impl(
                service=service, review_id=review_id
            )

        return await run_mcp_tool("list_research_sessions", call)
