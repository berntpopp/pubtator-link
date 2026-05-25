from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.mcp.annotations import (
    IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    READ_ONLY_OPEN_WORLD,
)
from pubtator_link.mcp.argument_aliases import coalesce_query, merge_pmids
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.tools import review as review_tools
from pubtator_link.mcp.tools.review._helpers import make_mcp_tool_for
from pubtator_link.models.review_rerag import (
    GroundQuestionResponse,
    ListResearchSessionsResponse,
    MaxResponseChars,
    PreflightReviewSourcesResponse,
    ResearchSessionStatusResponse,
    ReviewQuickstartResponse,
    ReviewResponseVerbosity,
    StageResearchSessionResponse,
)


def register_research_tools(mcp: FastMCP, profile: MCPToolProfile) -> None:
    mcp_tool_for = make_mcp_tool_for(mcp, profile)

    @mcp_tool_for(
        "lean",
        "full",
        "readonly",
        name="pubtator_preflight_review_sources",
        title="Preflight Review Sources",
        output_schema=PreflightReviewSourcesResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def preflight_review_sources(
        pmids: list[str] | None = None,
        pmid: str | None = None,
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
            "pubtator_preflight_review_sources",
            call,
            pmids=tool_pmids,
            fallback_tool="pubtator_get_publication_passages" if tool_pmids else None,
            fallback_args={"pmids": tool_pmids, "mode": "full_abstract"} if tool_pmids else None,
        )

    @mcp_tool_for(
        "full",
        name="pubtator_stage_research_session",
        title="Stage Research Session",
        output_schema=StageResearchSessionResponse.model_json_schema(),
        annotations=NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    )
    async def stage_research_session(
        review_id: Annotated[str, Field(min_length=1)],
        query: Annotated[str | None, Field(min_length=1)] = None,
        pmids: list[str] | None = None,
        pmid: Annotated[str | None, Field(min_length=1)] = None,
        session_id: Annotated[str | None, Field(min_length=1)] = None,
        page: Annotated[int, Field(ge=1, le=1000)] = 1,
        sort: str | None = None,
        filters: str | None = None,
        publication_types: list[str] | None = None,
        year_min: Annotated[int | None, Field(ge=1800, le=2030)] = None,
        year_max: Annotated[int | None, Field(ge=1800, le=2030)] = None,
        sections: list[str] | None = None,
        max_candidates: Annotated[int, Field(ge=1, le=100)] = 20,
        stage_full_text: bool = True,
    ) -> dict[str, Any]:
        """Use this when a user needs to stage candidate PMIDs with coverage hints and queued review preparation after search planning."""

        async def call() -> dict[str, Any]:
            selected_pmids = merge_pmids(pmids, pmid) if pmids or pmid else None
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
                publication_types=publication_types,
                year_min=year_min,
                year_max=year_max,
                sections=sections,
                max_candidates=max_candidates,
                stage_full_text=stage_full_text,
            )

        try:
            tool_pmids = merge_pmids(pmids, pmid)
        except ValueError:
            tool_pmids = None
        return await run_mcp_tool(
            "pubtator_stage_research_session",
            call,
            pmids=tool_pmids or [],
        )

    @mcp_tool_for(
        "lean",
        "full",
        name="pubtator_ground_question",
        title="Ground Question",
        output_schema=GroundQuestionResponse.model_json_schema(),
        annotations=IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    )
    async def ground_question(
        question: Annotated[str | None, Field(min_length=1)] = None,
        query: Annotated[str | None, Field(min_length=1)] = None,
        max_pmids: Annotated[int, Field(ge=1, le=20)] = 8,
        max_results: Annotated[int | None, Field(ge=1, le=20)] = None,
        review_id: Annotated[str | None, Field(min_length=1)] = None,
        entity_ids: list[str] | None = None,
        guideline_boost: bool = True,
        wait_until_ready: bool = True,
        timeout_ms: Annotated[int, Field(ge=0, le=120_000)] = 30_000,
        verbosity: ReviewResponseVerbosity = "lean",
        max_response_chars: MaxResponseChars = "auto",
    ) -> dict[str, Any]:
        """Use this when a user wants one compact grounded evidence workflow from a question: search literature, index candidate PMIDs, inspect readiness, and retrieve citable review context."""

        async def call() -> dict[str, Any]:
            selected_question = coalesce_query(question, query)
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

        return await run_mcp_tool("pubtator_ground_question", call)

    @mcp_tool_for(
        "full",
        name="pubtator_review_quickstart",
        title="Review Quickstart",
        output_schema=ReviewQuickstartResponse.model_json_schema(),
        annotations=NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    )
    async def review_quickstart(
        topic: Annotated[str | None, Field(min_length=1)] = None,
        query: Annotated[str | None, Field(min_length=1)] = None,
        question: Annotated[str | None, Field(min_length=1)] = None,
        n_pmids: Annotated[int, Field(ge=1, le=20)] = 8,
        review_id: Annotated[str | None, Field(min_length=1)] = None,
        session_id: Annotated[str | None, Field(min_length=1)] = None,
        wait_until_ready: bool = False,
        timeout_ms: Annotated[int, Field(ge=0, le=120_000)] = 0,
    ) -> dict[str, Any]:
        """Use this when a user wants one-shot casual review setup: search topic, stage/index up to n_pmids, inspect coverage, and return review_id/session_id for retrieve_review_context_batch."""

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

        return await run_mcp_tool("pubtator_review_quickstart", call)

    @mcp_tool_for(
        "full",
        "readonly",
        name="pubtator_get_research_session_status",
        title="Get Research Session Status",
        output_schema=ResearchSessionStatusResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_research_session_status(review_id: str, session_id: str) -> dict[str, Any]:
        """Use this when a user needs staged candidate, coverage, and preparation status for a research session."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_research_session_service()
            return await review_tools.get_research_session_status_impl(
                service=service,
                review_id=review_id,
                session_id=session_id,
            )

        return await run_mcp_tool("pubtator_get_research_session_status", call)

    @mcp_tool_for(
        "full",
        "readonly",
        name="pubtator_list_research_sessions",
        title="List Research Sessions",
        output_schema=ListResearchSessionsResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def list_research_sessions(review_id: str) -> dict[str, Any]:
        """Use this when a user needs staged research sessions for one review ID."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_research_session_service()
            return await review_tools.list_research_sessions_impl(
                service=service, review_id=review_id
            )

        return await run_mcp_tool("pubtator_list_research_sessions", call)
