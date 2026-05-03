from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal, cast

from fastmcp import Context, FastMCP
from pydantic import Field

from pubtator_link.api.routes.dependencies import (
    get_api_client,
    get_llm_review_context_service,
    get_research_session_service,
    get_review_audit_service,
    get_review_context_service,
    get_review_evidence_certainty_service,
    get_review_index_lifecycle_service,
    get_review_queue,
    get_source_preflight_service,
)
from pubtator_link.mcp.annotations import (
    FILE_EXPORT_ANNOTATIONS,
    READ_ONLY_OPEN_WORLD,
    REVIEW_WRITE_ANNOTATIONS,
)
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.service_adapters import (
    add_evidence_certainty_impl,
    export_review_audit_bundle_impl,
    get_evidence_certainty_impl,
    get_neighboring_review_passages_impl,
    get_research_session_status_impl,
    get_review_audit_trail_impl,
    get_review_index_summary_impl,
    get_review_passages_by_id_impl,
    ground_question_impl,
    index_review_evidence_impl,
    inspect_review_index_impl,
    list_evidence_certainty_impl,
    list_research_sessions_impl,
    list_review_indexes_impl,
    preflight_review_sources_impl,
    record_review_context_impl,
    retrieve_review_context_batch_impl,
    retrieve_review_context_impl,
    review_quickstart_impl,
    stage_research_session_impl,
)
from pubtator_link.models.review_rerag import (
    BudgetStrategy,
    EvidenceCertaintyLabel,
    EvidenceCertaintyResponse,
    GroundQuestionResponse,
    IndexReviewEvidenceResponse,
    InspectReviewIndexResponse,
    ListEvidenceCertaintyResponse,
    ListResearchSessionsResponse,
    ListReviewIndexesResponse,
    McpReviewAuditBundleResponse,
    PreflightReviewSourcesResponse,
    RecordReviewContextResponse,
    ResearchSessionStatusResponse,
    RetrieveReviewContextBatchResponse,
    RetrieveReviewContextResponse,
    ReviewAuditTrailResponse,
    ReviewBatchResponseMode,
    ReviewIndexSummaryResponse,
    ReviewLlmContextEventType,
    ReviewPassageLookupResponse,
    ReviewQuickstartResponse,
    ReviewTableMode,
    SampleSectionPolicy,
    StageResearchSessionResponse,
)


async def _warn_if_degraded(ctx: Context | None, result: dict[str, Any]) -> None:
    degraded_mode = result.get("degraded_mode")
    if ctx is not None and degraded_mode:
        await ctx.warning(
            "Review evidence is degraded: "
            f"{degraded_mode}. Inspect coverage before relying on passage-level claims.",
        )


async def _report_index_progress(
    ctx: Context | None,
    *,
    progress: float,
    total: float = 100,
) -> None:
    if ctx is not None:
        await ctx.report_progress(progress=progress, total=total)


def register_review_tools(mcp: FastMCP, profile: MCPToolProfile = "lean") -> None:
    def mcp_tool_for(
        *profiles: MCPToolProfile, **tool_kwargs: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            if profile in profiles:
                return cast(Callable[..., Any], mcp.tool(**tool_kwargs)(fn))
            return fn

        return decorator

    @mcp_tool_for(
        "full",
        "readonly",
        name="pubtator.list_review_indexes",
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
            service = await get_review_index_lifecycle_service()
            return await list_review_indexes_impl(service=service, limit=limit, offset=offset)

        return await run_mcp_tool("pubtator.list_review_indexes", call)

    @mcp_tool_for(
        "full",
        "readonly",
        name="pubtator.get_review_index_summary",
        title="Get Review Index Summary",
        output_schema=ReviewIndexSummaryResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_review_index_summary(review_id: str) -> dict[str, Any]:
        """Use this when a user needs one persisted review index summary without loading passage samples."""

        async def call() -> dict[str, Any]:
            service = await get_review_index_lifecycle_service()
            return await get_review_index_summary_impl(service=service, review_id=review_id)

        return await run_mcp_tool("pubtator.get_review_index_summary", call)

    @mcp_tool_for(
        "full",
        name="pubtator.add_evidence_certainty",
        title="Add Evidence Certainty",
        output_schema=EvidenceCertaintyResponse.model_json_schema(),
        annotations=REVIEW_WRITE_ANNOTATIONS,
    )
    async def add_evidence_certainty(
        review_id: str,
        outcome: str,
        question: str | None = None,
        study_design: str | None = None,
        risk_of_bias_notes: str | None = None,
        inconsistency_notes: str | None = None,
        indirectness_notes: str | None = None,
        imprecision_notes: str | None = None,
        publication_bias_notes: str | None = None,
        overall_certainty: EvidenceCertaintyLabel = "not_rated",
        certainty_rationale: str | None = None,
        passage_ids: list[str] | None = None,
        created_by: str | None = None,
        validate_passages: bool = False,
    ) -> dict[str, Any]:
        """Use this when a user needs to store a user-supplied GRADE-style evidence certainty judgment linked to prepared passage IDs. The backend stores the judgment; it does not compute certainty."""

        async def call() -> dict[str, Any]:
            service = await get_review_evidence_certainty_service()
            return await add_evidence_certainty_impl(
                service=service,
                review_id=review_id,
                outcome=outcome,
                question=question,
                study_design=study_design,
                risk_of_bias_notes=risk_of_bias_notes,
                inconsistency_notes=inconsistency_notes,
                indirectness_notes=indirectness_notes,
                imprecision_notes=imprecision_notes,
                publication_bias_notes=publication_bias_notes,
                overall_certainty=overall_certainty,
                certainty_rationale=certainty_rationale,
                passage_ids=passage_ids,
                created_by=created_by,
                validate_passages=validate_passages,
            )

        return await run_mcp_tool("pubtator.add_evidence_certainty", call)

    @mcp_tool_for(
        "full",
        "readonly",
        name="pubtator.list_evidence_certainty",
        title="List Evidence Certainty",
        output_schema=ListEvidenceCertaintyResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def list_evidence_certainty(review_id: str) -> dict[str, Any]:
        """Use this when a user needs user-supplied evidence certainty judgments for a review."""

        async def call() -> dict[str, Any]:
            service = await get_review_evidence_certainty_service()
            return await list_evidence_certainty_impl(service=service, review_id=review_id)

        return await run_mcp_tool("pubtator.list_evidence_certainty", call)

    @mcp_tool_for(
        "full",
        "readonly",
        name="pubtator.get_evidence_certainty",
        title="Get Evidence Certainty",
        output_schema=EvidenceCertaintyResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_evidence_certainty(review_id: str, certainty_id: str) -> dict[str, Any]:
        """Use this when a user needs one user-supplied evidence certainty judgment."""

        async def call() -> dict[str, Any]:
            service = await get_review_evidence_certainty_service()
            return await get_evidence_certainty_impl(
                service=service,
                review_id=review_id,
                certainty_id=certainty_id,
            )

        return await run_mcp_tool("pubtator.get_evidence_certainty", call)

    @mcp_tool_for(
        "lean",
        "full",
        "readonly",
        name="pubtator.preflight_review_sources",
        title="Preflight Review Sources",
        output_schema=PreflightReviewSourcesResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def preflight_review_sources(
        pmids: list[str],
    ) -> dict[str, Any]:
        """Use this when a user needs PMID source coverage, PMC fallback availability, and likely full-text versus abstract-only retrieval before indexing review evidence."""

        async def call() -> dict[str, Any]:
            service = await get_source_preflight_service()
            return await preflight_review_sources_impl(service=service, pmids=pmids)

        return await run_mcp_tool("pubtator.preflight_review_sources", call, pmids=pmids)

    @mcp_tool_for(
        "full",
        name="pubtator.stage_research_session",
        title="Stage Research Session",
        output_schema=StageResearchSessionResponse.model_json_schema(),
        annotations=REVIEW_WRITE_ANNOTATIONS,
    )
    async def stage_research_session(
        review_id: Annotated[str, Field(min_length=1)],
        query: Annotated[str | None, Field(min_length=1)] = None,
        pmids: list[str] | None = None,
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
            service = await get_research_session_service()
            return await stage_research_session_impl(
                service=service,
                review_id=review_id,
                query=query,
                pmids=pmids,
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

        return await run_mcp_tool(
            "pubtator.stage_research_session",
            call,
            pmids=pmids or [],
        )

    @mcp_tool_for(
        "lean",
        "full",
        name="pubtator.ground_question",
        title="Ground Question",
        output_schema=GroundQuestionResponse.model_json_schema(),
        annotations=REVIEW_WRITE_ANNOTATIONS,
    )
    async def ground_question(
        question: Annotated[str, Field(min_length=1)],
        max_pmids: Annotated[int, Field(ge=1, le=20)] = 8,
        review_id: Annotated[str | None, Field(min_length=1)] = None,
        entity_ids: list[str] | None = None,
        guideline_boost: bool = True,
        wait_until_ready: bool = True,
        timeout_ms: Annotated[int, Field(ge=0, le=120_000)] = 30_000,
    ) -> dict[str, Any]:
        """Use this when a user wants one compact grounded evidence workflow from a question: search literature, index candidate PMIDs, inspect readiness, and retrieve citable review context."""

        async def call() -> dict[str, Any]:
            client = await get_api_client()
            queue = await get_review_queue()
            context_service = await get_review_context_service()
            return await ground_question_impl(
                client=client,
                queue=queue,
                context_service=context_service,
                question=question,
                max_pmids=max_pmids,
                review_id=review_id,
                entity_ids=entity_ids,
                guideline_boost=guideline_boost,
                wait_until_ready=wait_until_ready,
                timeout_ms=timeout_ms,
            )

        return await run_mcp_tool("pubtator.ground_question", call)

    @mcp_tool_for(
        "full",
        name="pubtator.review_quickstart",
        title="Review Quickstart",
        output_schema=ReviewQuickstartResponse.model_json_schema(),
        annotations=REVIEW_WRITE_ANNOTATIONS,
    )
    async def review_quickstart(
        topic: Annotated[str, Field(min_length=1)],
        n_pmids: Annotated[int, Field(ge=1, le=20)] = 8,
        review_id: Annotated[str | None, Field(min_length=1)] = None,
        session_id: Annotated[str | None, Field(min_length=1)] = None,
        wait_until_ready: bool = False,
        timeout_ms: Annotated[int, Field(ge=0, le=120_000)] = 0,
    ) -> dict[str, Any]:
        """Use this when a user wants one-shot casual review setup: search topic, stage/index up to n_pmids, inspect coverage, and return review_id/session_id for retrieve_review_context_batch."""

        async def call() -> dict[str, Any]:
            stage_service = await get_research_session_service()
            context_service = await get_review_context_service()
            return await review_quickstart_impl(
                stage_service=stage_service,
                context_service=context_service,
                topic=topic,
                n_pmids=n_pmids,
                review_id=review_id,
                session_id=session_id,
                wait_until_ready=wait_until_ready,
                timeout_ms=timeout_ms,
            )

        return await run_mcp_tool("pubtator.review_quickstart", call)

    @mcp_tool_for(
        "full",
        "readonly",
        name="pubtator.get_research_session_status",
        title="Get Research Session Status",
        output_schema=ResearchSessionStatusResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_research_session_status(review_id: str, session_id: str) -> dict[str, Any]:
        """Use this when a user needs staged candidate, coverage, and preparation status for a research session."""

        async def call() -> dict[str, Any]:
            service = await get_research_session_service()
            return await get_research_session_status_impl(
                service=service,
                review_id=review_id,
                session_id=session_id,
            )

        return await run_mcp_tool("pubtator.get_research_session_status", call)

    @mcp_tool_for(
        "full",
        "readonly",
        name="pubtator.list_research_sessions",
        title="List Research Sessions",
        output_schema=ListResearchSessionsResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def list_research_sessions(review_id: str) -> dict[str, Any]:
        """Use this when a user needs staged research sessions for one review ID."""

        async def call() -> dict[str, Any]:
            service = await get_research_session_service()
            return await list_research_sessions_impl(service=service, review_id=review_id)

        return await run_mcp_tool("pubtator.list_research_sessions", call)

    @mcp_tool_for(
        "lean",
        "full",
        name="pubtator.index_review_evidence",
        title="Index Review Evidence",
        output_schema=IndexReviewEvidenceResponse.model_json_schema(),
        annotations=REVIEW_WRITE_ANNOTATIONS,
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
        """Use this when a review needs review-scoped evidence preparation for a review_id and PMIDs/curated URLs. Call this before retrieve_review_context_batch, use session_id to scope staged research sessions, set wait_until_ready for small corpora, and inspect preparation_status before retrieval."""

        async def call() -> dict[str, Any]:
            queue = await get_review_queue()
            if wait_until_ready:
                await _report_index_progress(ctx, progress=0)
            result = await index_review_evidence_impl(
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
            "pubtator.index_review_evidence",
            call,
            pmids=pmids or [],
        )

    @mcp_tool_for(
        "lean",
        "full",
        "readonly",
        name="pubtator.inspect_review_index",
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
    ) -> dict[str, Any]:
        """Use this when a user needs to inspect indexed PMIDs, sections, passage counts, and failures for a review_id, including source coverage."""

        async def call() -> dict[str, Any]:
            service = await get_review_context_service()
            return await inspect_review_index_impl(
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
            )

        return await run_mcp_tool("pubtator.inspect_review_index", call, pmids=pmids)

    @mcp_tool_for(
        "full",
        "readonly",
        name="pubtator.get_review_passages_by_id",
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
            service = await get_review_context_service()
            return await get_review_passages_by_id_impl(
                service=service,
                review_id=review_id,
                passage_ids=passage_ids,
                session_id=session_id,
                max_chars_per_passage=max_chars_per_passage,
            )

        return await run_mcp_tool("pubtator.get_review_passages_by_id", call)

    @mcp_tool_for(
        "lean",
        "full",
        "readonly",
        name="pubtator.get_review_audit_trail",
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
            service = await get_review_context_service()
            return await get_review_audit_trail_impl(
                service=service,
                review_id=review_id,
                passage_ids=passage_ids,
                session_id=session_id,
                max_chars_per_passage=max_chars_per_passage,
            )

        return await run_mcp_tool("pubtator.get_review_audit_trail", call)

    @mcp_tool_for(
        "full",
        "readonly",
        name="pubtator.get_neighboring_review_passages",
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
            service = await get_review_context_service()
            return await get_neighboring_review_passages_impl(
                service=service,
                review_id=review_id,
                passage_id=passage_id,
                session_id=session_id,
                before=before,
                after=after,
                same_section=same_section,
                max_chars_per_passage=max_chars_per_passage,
            )

        return await run_mcp_tool("pubtator.get_neighboring_review_passages", call)

    @mcp_tool_for(
        "full",
        name="pubtator.export_review_audit_bundle",
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
            service = await get_review_audit_service()
            return await export_review_audit_bundle_impl(
                service=service,
                review_id=review_id,
                session_id=session_id,
                export_path=export_path,
                fallback_inline=fallback_inline,
            )

        return await run_mcp_tool("pubtator.export_review_audit_bundle", call)

    @mcp_tool_for(
        "full",
        "readonly",
        name="pubtator.retrieve_review_context",
        title="Retrieve Review Context",
        output_schema=RetrieveReviewContextResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def retrieve_review_context(
        review_id: str,
        question: str,
        session_id: str | None = None,
        pmids: list[str] | None = None,
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
        """Use this when a review needs compact citable context from prepared review passages instead of raw BioC export. Use a short keyword query, PMID filters for paper-specific evidence, and diagnostics for zero-result debugging. If zero passages are returned, simplify the query, inspect the review index, or fall back to fetch_publication_annotations."""

        async def call() -> dict[str, Any]:
            service = await get_review_context_service()
            result = await retrieve_review_context_impl(
                service=service,
                review_id=review_id,
                question=question,
                session_id=session_id,
                pmids=pmids,
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

        return await run_mcp_tool("pubtator.retrieve_review_context", call, pmids=pmids)

    @mcp_tool_for(
        "lean",
        "full",
        "readonly",
        name="pubtator.retrieve_review_context_batch",
        title="Retrieve Review Context Batch",
        output_schema=RetrieveReviewContextBatchResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def retrieve_review_context_batch(
        review_id: str,
        queries: list[str],
        session_id: str | None = None,
        pmids: list[str] | None = None,
        entity_ids: list[str] | None = None,
        sections: list[str] | None = None,
        response_mode: ReviewBatchResponseMode = "compact",
        max_passages_per_query: int = 8,
        max_total_passages: int = 20,
        max_chars: int | None = None,
        max_response_chars: int | None = None,
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
            service = await get_review_context_service()
            result = await retrieve_review_context_batch_impl(
                service=service,
                review_id=review_id,
                queries=queries,
                session_id=session_id,
                pmids=pmids,
                entity_ids=entity_ids,
                sections=sections,
                response_mode=response_mode,
                max_passages_per_query=max_passages_per_query,
                max_total_passages=max_total_passages,
                max_chars=max_chars,
                max_response_chars=max_response_chars,
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

        return await run_mcp_tool(
            "pubtator.retrieve_review_context_batch",
            call,
            pmids=pmids,
        )

    @mcp_tool_for(
        "lean",
        "full",
        name="pubtator.record_review_context",
        title="Record Review Context",
        output_schema=RecordReviewContextResponse.model_json_schema(),
        annotations=REVIEW_WRITE_ANNOTATIONS,
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
            service = await get_llm_review_context_service()
            return await record_review_context_impl(
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

        return await run_mcp_tool("pubtator.record_review_context", call)
