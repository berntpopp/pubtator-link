from __future__ import annotations

from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field

from pubtator_link.mcp.annotations import (
    NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    READ_ONLY_OPEN_WORLD,
)
from pubtator_link.mcp.argument_aliases import merge_pmids
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.meta_budget import strip_meta_for_repeated_call
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.tools import review as review_tools
from pubtator_link.mcp.tools.review._helpers import _warn_if_degraded, make_mcp_tool_for
from pubtator_link.models.review_rerag import (
    BudgetStrategy,
    MaxResponseChars,
    ReviewBatchResponseMode,
    ReviewLlmContextEventType,
    ReviewResponseVerbosity,
    ReviewTableMode,
    SampleSectionPolicy,
)

_STR_ITEM = Field(min_length=1)


def register_retrieval_tools(mcp: FastMCP, profile: MCPToolProfile) -> None:
    mcp_tool_for = make_mcp_tool_for(mcp, profile)

    @mcp_tool_for(
        "full",
        "readonly",
        name="get_review_context",
        title="Retrieve Review Context",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def retrieve_review_context(
        review_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Prepared review index to retrieve citable context from.",
                examples=["demo"],
            ),
        ],
        question: Annotated[
            str,
            Field(
                min_length=1,
                description="Short keyword retrieval question or query.",
                examples=["EGFR resistance"],
            ),
        ],
        session_id: Annotated[
            str | None, Field(description="Optional staged session to scope retrieval to.")
        ] = None,
        pmids: Annotated[
            list[str] | None,
            Field(description="Restrict retrieval to these PMIDs.", examples=[["12345"]]),
        ] = None,
        entity_ids: Annotated[
            list[str] | None,
            Field(
                description="Restrict retrieval to these PubTator entity IDs.",
                examples=[["@GENE_BRCA1"]],
            ),
        ] = None,
        sections: Annotated[
            list[str] | None,
            Field(
                description="Restrict retrieval to these article sections.", examples=[["abstract"]]
            ),
        ] = None,
        max_passages: Annotated[
            int, Field(ge=1, le=100, description="Maximum passages to return.")
        ] = 8,
        max_chars: Annotated[
            int, Field(ge=200, le=60_000, description="Soft total character budget for passages.")
        ] = 6000,
        include_diagnostics: Annotated[
            bool, Field(description="Include retrieval diagnostics in the response.")
        ] = False,
        include_tables: Annotated[bool, Field(description="Include table passages.")] = False,
        include_references: Annotated[
            bool, Field(description="Include reference-list passages.")
        ] = False,
        table_mode: Annotated[
            ReviewTableMode,
            Field(description="Table rendering: 'off', 'preview' (default), or 'full'."),
        ] = "preview",
        section_policy: Annotated[
            SampleSectionPolicy,
            Field(description="Passage ordering: 'evidence_first' (default) or 'original_order'."),
        ] = "evidence_first",
        allow_truncated_passages: Annotated[
            bool, Field(description="Allow per-passage truncation to fit the char budget.")
        ] = True,
        max_chars_per_passage: Annotated[
            int, Field(ge=100, le=20000, description="Character cap per returned passage.")
        ] = 2200,
        include_resolver_trace: Annotated[
            bool, Field(description="Include the source-resolver trace for auditing.")
        ] = False,
        include_meta: Annotated[
            bool, Field(description="Include the _meta orientation block.")
        ] = True,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Use this when a review needs compact citable context from prepared review passages instead of raw BioC export. Use a short keyword query and PMID filters. If zero passages are returned, simplify the query, inspect the review index, or fall back to get_publication_annotations."""

        async def call() -> dict[str, Any]:
            selected_question = question
            selected_pmids = merge_pmids(pmids, None, max_items=100) if pmids else None
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
                profile=profile,
            )
            await _warn_if_degraded(ctx, result)
            return result

        try:
            tool_pmids = merge_pmids(pmids, None, max_items=100)
        except ValueError:
            tool_pmids = None
        result = await run_mcp_tool("get_review_context", call, pmids=tool_pmids)
        return result if include_meta else strip_meta_for_repeated_call(result)

    @mcp_tool_for(
        "lean",
        "full",
        "readonly",
        name="get_review_context_batch",
        title="Retrieve Review Context Batch",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def retrieve_review_context_batch(
        review_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Prepared review index to retrieve citable context from.",
                examples=["demo"],
            ),
        ],
        queries: Annotated[
            list[str],
            Field(
                min_length=1,
                description="Short keyword query variants to retrieve context for in one call.",
                examples=[["EGFR resistance", "osimertinib resistance"]],
            ),
        ],
        session_id: Annotated[
            str | None, Field(description="Optional staged session to scope retrieval to.")
        ] = None,
        pmids: Annotated[
            list[str] | None,
            Field(description="Restrict retrieval to these PMIDs.", examples=[["12345"]]),
        ] = None,
        entity_ids: Annotated[
            list[str] | None,
            Field(
                description="Restrict retrieval to these PubTator entity IDs.",
                examples=[["@GENE_EGFR"]],
            ),
        ] = None,
        sections: Annotated[
            list[str] | None,
            Field(
                description="Restrict retrieval to these article sections.", examples=[["abstract"]]
            ),
        ] = None,
        response_mode: Annotated[
            ReviewBatchResponseMode,
            Field(description="Payload shape (default 'compact'); 'quotes' for short snippets."),
        ] = "compact",
        max_passages_per_query: Annotated[
            int, Field(ge=1, le=50, description="Maximum passages per query variant.")
        ] = 8,
        max_total_passages: Annotated[
            int, Field(ge=1, le=200, description="Maximum passages across all queries.")
        ] = 20,
        max_chars: Annotated[
            int | None,
            Field(ge=200, le=200_000, description="Optional soft total character budget."),
        ] = None,
        max_response_chars: Annotated[
            MaxResponseChars,
            Field(description="Response character budget: 'auto' (default) or an integer cap."),
        ] = "auto",
        verbosity: Annotated[
            ReviewResponseVerbosity,
            Field(description="Field verbosity: 'lean', 'standard' (default), or 'full'."),
        ] = "standard",
        deduplicate_passages: Annotated[
            bool, Field(description="Merge duplicate passages across query variants.")
        ] = True,
        budget_strategy: Annotated[
            BudgetStrategy | None,
            Field(description="Passage budget split (default 'query_fair')."),
        ] = "query_fair",
        min_passages_per_source: Annotated[
            int, Field(ge=0, le=50, description="Guaranteed minimum passages per source.")
        ] = 1,
        min_passages_per_pmid: Annotated[
            int, Field(ge=0, le=50, description="Guaranteed minimum passages per PMID.")
        ] = 0,
        prioritize_pmids: Annotated[
            list[str] | None,
            Field(description="PMIDs to prioritize in budgeting.", examples=[["12345"]]),
        ] = None,
        include_diagnostics: Annotated[
            bool, Field(description="Include retrieval diagnostics in the response.")
        ] = False,
        include_tables: Annotated[bool, Field(description="Include table passages.")] = False,
        include_references: Annotated[
            bool, Field(description="Include reference-list passages.")
        ] = False,
        table_mode: Annotated[
            ReviewTableMode,
            Field(description="Table rendering: 'off', 'preview' (default), or 'full'."),
        ] = "preview",
        section_policy: Annotated[
            SampleSectionPolicy,
            Field(description="Passage ordering: 'evidence_first' (default) or 'original_order'."),
        ] = "evidence_first",
        allow_truncated_passages: Annotated[
            bool, Field(description="Allow per-passage truncation to fit the char budget.")
        ] = True,
        max_chars_per_passage: Annotated[
            int, Field(ge=100, le=20000, description="Character cap per returned passage.")
        ] = 2200,
        dry_run: Annotated[
            bool, Field(description="Return budgeting diagnostics without passage text.")
        ] = False,
        include_resolver_trace: Annotated[
            bool, Field(description="Include the source-resolver trace for auditing.")
        ] = False,
        include_meta: Annotated[
            bool, Field(description="Include the _meta orientation block.")
        ] = True,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Use this when a user wants multiple short review retrieval query variants in one call. Default compact mode uses query_fair budgeting, merged passages, per-query summaries, and next_steps for zero-result queries. Use response_mode="quotes" for short citable snippets or dry_run for diagnostics without passage text."""

        async def call() -> dict[str, Any]:
            selected_pmids = merge_pmids(pmids, None, max_items=100) if pmids else None
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
                profile=profile,
            )
            await _warn_if_degraded(ctx, result)
            return result

        try:
            tool_pmids = merge_pmids(pmids, None, max_items=100)
        except ValueError:
            tool_pmids = None
        result = await run_mcp_tool(
            "get_review_context_batch",
            call,
            pmids=tool_pmids,
        )
        return result if include_meta else strip_meta_for_repeated_call(result)

    @mcp_tool_for(
        "lean",
        "full",
        name="record_review_context",
        title="Record Review Context",
        output_schema=None,
        annotations=NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    )
    async def record_review_context(
        review_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Review index to persist the LLM context event under.",
                examples=["demo"],
            ),
        ],
        event_type: Annotated[
            ReviewLlmContextEventType,
            Field(
                description="Kind of context event being recorded.",
                examples=["passage_selected"],
            ),
        ],
        session_id: Annotated[
            str | None, Field(min_length=1, description="Staged session this event belongs to.")
        ] = None,
        summary: Annotated[
            str | None,
            Field(max_length=4000, description="Short human-readable summary of the event."),
        ] = None,
        pmids: Annotated[
            list[Annotated[str, _STR_ITEM]] | None,
            Field(description="Cited PMIDs.", examples=[["12345"]]),
        ] = None,
        passage_ids: Annotated[
            list[Annotated[str, _STR_ITEM]] | None,
            Field(description="Cited passage IDs.", examples=[["p1"]]),
        ] = None,
        queries: Annotated[
            list[Annotated[str, _STR_ITEM]] | None,
            Field(
                description="Associated queries.",
                examples=[["EGFR resistance"]],
            ),
        ] = None,
        decision: Annotated[dict[str, Any] | None, Field(description="Decision payload.")] = None,
        topic: Annotated[
            str | None, Field(max_length=500, description="Topic label for the event.")
        ] = None,
        research_question: Annotated[
            str | None, Field(max_length=1000, description="Research question for the event.")
        ] = None,
        question_hash: Annotated[
            str | None, Field(max_length=128, description="Stable hash of the research question.")
        ] = None,
        request: Annotated[dict[str, Any] | None, Field(description="Request payload.")] = None,
        response_summary: Annotated[
            dict[str, Any] | None, Field(description="Response summary.")
        ] = None,
        selected_pmids: Annotated[
            list[Annotated[str, _STR_ITEM]] | None,
            Field(description="Selected PMIDs.", examples=[["12345"]]),
        ] = None,
        rejected_pmids: Annotated[
            list[Annotated[str, _STR_ITEM]] | None,
            Field(description="Rejected PMIDs.", examples=[["67890"]]),
        ] = None,
        preferred_entity_ids: Annotated[
            list[Annotated[str, _STR_ITEM]] | None,
            Field(description="Preferred entity IDs.", examples=[["@GENE_EGFR"]]),
        ] = None,
        selected_passage_ids: Annotated[
            list[Annotated[str, _STR_ITEM]] | None,
            Field(description="Answer passage IDs.", examples=[["p1"]]),
        ] = None,
        audit_passage_ids: Annotated[
            list[Annotated[str, _STR_ITEM]] | None,
            Field(description="Audit passage IDs.", examples=[["p1"]]),
        ] = None,
        active_queries: Annotated[
            list[Annotated[str, _STR_ITEM]] | None,
            Field(description="Active queries.", examples=[["EGFR resistance"]]),
        ] = None,
        successful_queries: Annotated[
            list[Annotated[str, _STR_ITEM]] | None,
            Field(description="Successful queries.", examples=[["EGFR resistance"]]),
        ] = None,
        failed_queries: Annotated[
            list[Annotated[str, _STR_ITEM]] | None,
            Field(description="Failed queries.", examples=[["EGFR resistence"]]),
        ] = None,
        open_questions: Annotated[
            list[dict[str, Any]] | None,
            Field(
                description="Open questions.",
                examples=[[{"question": "Does dose matter?", "status": "open"}]],
            ),
        ] = None,
        user_decisions: Annotated[
            list[dict[str, Any]] | None,
            Field(
                description="User decisions.",
                examples=[[{"decision": "include", "pmid": "12345"}]],
            ),
        ] = None,
        last_next_commands: Annotated[
            list[dict[str, Any]] | None,
            Field(
                description="The next_commands block last shown to the user.",
                examples=[[{"tool": "diagnostics", "arguments": {}}]],
            ),
        ] = None,
        stable_citation_keys: Annotated[
            dict[str, str] | None,
            Field(description="Passage/PMID to citation-key map."),
        ] = None,
        cache_key: Annotated[
            str | None, Field(max_length=500, description="Cache key for the recorded context.")
        ] = None,
        token_estimate: Annotated[
            int | None, Field(ge=0, description="Estimated token size.")
        ] = None,
        payload: Annotated[
            dict[str, Any] | None, Field(description="Arbitrary payload to persist.")
        ] = None,
        created_by: Annotated[
            str | None, Field(max_length=200, description="Recorded-by attribution.")
        ] = None,
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

        return await run_mcp_tool("record_review_context", call)
