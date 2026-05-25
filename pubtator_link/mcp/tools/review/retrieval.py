from __future__ import annotations

from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field

from pubtator_link.mcp.annotations import (
    NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    READ_ONLY_OPEN_WORLD,
)
from pubtator_link.mcp.argument_aliases import coalesce_query, merge_pmids
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.tools import review as review_tools
from pubtator_link.mcp.tools.review._helpers import _warn_if_degraded, make_mcp_tool_for
from pubtator_link.models.review_rerag import (
    BudgetStrategy,
    MaxResponseChars,
    RecordReviewContextResponse,
    RetrieveReviewContextBatchResponse,
    RetrieveReviewContextResponse,
    ReviewBatchResponseMode,
    ReviewLlmContextEventType,
    ReviewResponseVerbosity,
    ReviewTableMode,
    SampleSectionPolicy,
)


def register_retrieval_tools(mcp: FastMCP, profile: MCPToolProfile) -> None:
    mcp_tool_for = make_mcp_tool_for(mcp, profile)

    @mcp_tool_for(
        "full",
        "readonly",
        name="pubtator_retrieve_review_context",
        title="Retrieve Review Context",
        output_schema=RetrieveReviewContextResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def retrieve_review_context(
        review_id: str,
        question: str | None = None,
        query: str | None = None,
        session_id: str | None = None,
        pmids: list[str] | None = None,
        pmid: str | None = None,
        entity_ids: list[str] | None = None,
        sections: list[str] | None = None,
        max_passages: int = 8,
        max_chars: int = 6000,
        include_diagnostics: bool = False,
        include_tables: bool = False,
        include_references: bool = False,
        table_mode: ReviewTableMode = "preview",
        section_policy: SampleSectionPolicy = "evidence_first",
        allow_truncated_passages: bool = True,
        max_chars_per_passage: int = 2200,
        include_resolver_trace: bool = False,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Use this when a review needs compact citable context from prepared review passages instead of raw BioC export. Provide one of question or query. Use a short keyword query and PMID filters. If zero passages are returned, simplify the query, inspect the review index, or fall back to fetch_publication_annotations."""

        async def call() -> dict[str, Any]:
            selected_question = coalesce_query(question, query)
            selected_pmids = merge_pmids(pmids, pmid, max_items=100) if pmids or pmid else None
            service = await review_tools.get_review_context_service()
            result = await review_tools.retrieve_review_context_impl(
                service=service,
                review_id=review_id,
                question=selected_question,
                session_id=session_id,
                pmids=selected_pmids,
                entity_ids=entity_ids,
                sections=sections,
                max_passages=max_passages,
                max_chars=max_chars,
                include_diagnostics=include_diagnostics,
                include_tables=include_tables,
                include_references=include_references,
                table_mode=table_mode,
                section_policy=section_policy,
                allow_truncated_passages=allow_truncated_passages,
                max_chars_per_passage=max_chars_per_passage,
                include_resolver_trace=include_resolver_trace,
            )
            await _warn_if_degraded(ctx, result)
            return result

        try:
            tool_pmids = merge_pmids(pmids, pmid, max_items=100)
        except ValueError:
            tool_pmids = None
        return await run_mcp_tool("pubtator_retrieve_review_context", call, pmids=tool_pmids)

    @mcp_tool_for(
        "lean",
        "full",
        "readonly",
        name="pubtator_retrieve_review_context_batch",
        title="Retrieve Review Context Batch",
        output_schema=RetrieveReviewContextBatchResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def retrieve_review_context_batch(
        review_id: str,
        queries: list[str],
        session_id: str | None = None,
        pmids: list[str] | None = None,
        pmid: str | None = None,
        entity_ids: list[str] | None = None,
        sections: list[str] | None = None,
        response_mode: ReviewBatchResponseMode = "compact",
        max_passages_per_query: int = 8,
        max_total_passages: int = 20,
        max_chars: int | None = None,
        max_response_chars: MaxResponseChars = "auto",
        verbosity: ReviewResponseVerbosity = "standard",
        deduplicate_passages: bool = True,
        budget_strategy: BudgetStrategy | None = "query_fair",
        min_passages_per_source: int = 1,
        min_passages_per_pmid: int = 0,
        prioritize_pmids: list[str] | None = None,
        include_diagnostics: bool = False,
        include_tables: bool = False,
        include_references: bool = False,
        table_mode: ReviewTableMode = "preview",
        section_policy: SampleSectionPolicy = "evidence_first",
        allow_truncated_passages: bool = True,
        max_chars_per_passage: int = 2200,
        dry_run: bool = False,
        include_resolver_trace: bool = False,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Use this when a user wants multiple short review retrieval query variants in one call. Default compact mode uses query_fair budgeting, merged passages, per-query summaries, and next_steps for zero-result queries. Use response_mode="quotes" for short citable snippets or dry_run for diagnostics without passage text."""

        async def call() -> dict[str, Any]:
            selected_pmids = merge_pmids(pmids, pmid, max_items=100) if pmids or pmid else None
            service = await review_tools.get_review_context_service()
            result = await review_tools.retrieve_review_context_batch_impl(
                service=service,
                review_id=review_id,
                queries=queries,
                session_id=session_id,
                pmids=selected_pmids,
                entity_ids=entity_ids,
                sections=sections,
                response_mode=response_mode,
                max_passages_per_query=max_passages_per_query,
                max_total_passages=max_total_passages,
                max_chars=max_chars,
                max_response_chars=max_response_chars,
                verbosity=verbosity,
                deduplicate_passages=deduplicate_passages,
                budget_strategy=budget_strategy or "query_fair",
                min_passages_per_source=min_passages_per_source,
                min_passages_per_pmid=min_passages_per_pmid,
                prioritize_pmids=prioritize_pmids,
                include_diagnostics=include_diagnostics,
                include_tables=include_tables,
                include_references=include_references,
                table_mode=table_mode,
                section_policy=section_policy,
                allow_truncated_passages=allow_truncated_passages,
                max_chars_per_passage=max_chars_per_passage,
                dry_run=dry_run,
                include_resolver_trace=include_resolver_trace,
            )
            await _warn_if_degraded(ctx, result)
            return result

        try:
            tool_pmids = merge_pmids(pmids, pmid, max_items=100)
        except ValueError:
            tool_pmids = None
        return await run_mcp_tool(
            "pubtator_retrieve_review_context_batch",
            call,
            pmids=tool_pmids,
        )

    @mcp_tool_for(
        "lean",
        "full",
        name="pubtator_record_review_context",
        title="Record Review Context",
        output_schema=RecordReviewContextResponse.model_json_schema(),
        annotations=NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    )
    async def record_review_context(
        review_id: Annotated[str, Field(min_length=1)],
        event_type: ReviewLlmContextEventType,
        session_id: Annotated[str | None, Field(min_length=1)] = None,
        summary: Annotated[str | None, Field(max_length=4000)] = None,
        pmids: list[Annotated[str, Field(min_length=1)]] | None = None,
        passage_ids: list[Annotated[str, Field(min_length=1)]] | None = None,
        queries: list[Annotated[str, Field(min_length=1)]] | None = None,
        decision: dict[str, Any] | None = None,
        topic: Annotated[str | None, Field(max_length=500)] = None,
        research_question: Annotated[str | None, Field(max_length=1000)] = None,
        question_hash: Annotated[str | None, Field(max_length=128)] = None,
        request: dict[str, Any] | None = None,
        response_summary: dict[str, Any] | None = None,
        selected_pmids: list[Annotated[str, Field(min_length=1)]] | None = None,
        rejected_pmids: list[Annotated[str, Field(min_length=1)]] | None = None,
        preferred_entity_ids: list[Annotated[str, Field(min_length=1)]] | None = None,
        selected_passage_ids: list[Annotated[str, Field(min_length=1)]] | None = None,
        audit_passage_ids: list[Annotated[str, Field(min_length=1)]] | None = None,
        active_queries: list[Annotated[str, Field(min_length=1)]] | None = None,
        successful_queries: list[Annotated[str, Field(min_length=1)]] | None = None,
        failed_queries: list[Annotated[str, Field(min_length=1)]] | None = None,
        open_questions: list[dict[str, Any]] | None = None,
        user_decisions: list[dict[str, Any]] | None = None,
        last_next_commands: list[dict[str, Any]] | None = None,
        stable_citation_keys: dict[str, str] | None = None,
        cache_key: Annotated[str | None, Field(max_length=500)] = None,
        token_estimate: Annotated[int | None, Field(ge=0)] = None,
        payload: dict[str, Any] | None = None,
        created_by: Annotated[str | None, Field(max_length=200)] = None,
    ) -> dict[str, Any]:
        """Use this when a user needs to persist compact LLM review context, selected evidence IDs, decisions, or next-step state without storing article text."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_llm_review_context_service()
            return await review_tools.record_review_context_impl(
                service=service,
                review_id=review_id,
                event_type=event_type,
                session_id=session_id,
                summary=summary,
                pmids=pmids,
                passage_ids=passage_ids,
                queries=queries,
                decision=decision,
                topic=topic,
                research_question=research_question,
                question_hash=question_hash,
                request=request,
                response_summary=response_summary,
                selected_pmids=selected_pmids,
                rejected_pmids=rejected_pmids,
                preferred_entity_ids=preferred_entity_ids,
                selected_passage_ids=selected_passage_ids,
                audit_passage_ids=audit_passage_ids,
                active_queries=active_queries,
                successful_queries=successful_queries,
                failed_queries=failed_queries,
                open_questions=open_questions,
                user_decisions=user_decisions,
                last_next_commands=last_next_commands,
                stable_citation_keys=stable_citation_keys,
                cache_key=cache_key,
                token_estimate=token_estimate,
                payload=payload,
                created_by=created_by,
            )

        return await run_mcp_tool("pubtator_record_review_context", call)
