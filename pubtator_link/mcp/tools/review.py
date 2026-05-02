from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.api.routes.dependencies import (
    get_research_session_service,
    get_review_audit_service,
    get_review_context_service,
    get_review_evidence_certainty_service,
    get_review_index_lifecycle_service,
    get_review_queue,
    get_source_preflight_service,
)
from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD, REVIEW_WRITE_ANNOTATIONS
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.service_adapters import (
    add_evidence_certainty_impl,
    export_review_audit_bundle_impl,
    get_evidence_certainty_impl,
    get_neighboring_review_passages_impl,
    get_research_session_status_impl,
    get_review_index_summary_impl,
    get_review_passages_by_id_impl,
    index_review_evidence_impl,
    inspect_review_index_impl,
    list_evidence_certainty_impl,
    list_research_sessions_impl,
    list_review_indexes_impl,
    preflight_review_sources_impl,
    retrieve_review_context_batch_impl,
    retrieve_review_context_impl,
    stage_research_session_impl,
)
from pubtator_link.models.review_rerag import (
    BudgetStrategy,
    EvidenceCertaintyLabel,
    EvidenceCertaintyResponse,
    IndexReviewEvidenceResponse,
    InspectReviewIndexResponse,
    ListEvidenceCertaintyResponse,
    ListResearchSessionsResponse,
    ListReviewIndexesResponse,
    McpReviewAuditBundleResponse,
    PreflightReviewSourcesResponse,
    ResearchSessionStatusResponse,
    RetrieveReviewContextBatchResponse,
    RetrieveReviewContextResponse,
    ReviewBatchResponseMode,
    ReviewIndexSummaryResponse,
    ReviewPassageLookupResponse,
    ReviewTableMode,
    SampleSectionPolicy,
    StageResearchSessionResponse,
)


def register_review_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="pubtator.list_review_indexes",
        title="List Review Indexes",
        output_schema=ListReviewIndexesResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def list_review_indexes(
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Use this to list persisted review indexes with preparation status, source counts, passage counts, and approximate storage size. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""

        async def call() -> dict[str, Any]:
            service = await get_review_index_lifecycle_service()
            return await list_review_indexes_impl(service=service, limit=limit, offset=offset)

        return await run_mcp_tool("pubtator.list_review_indexes", call)

    @mcp.tool(
        name="pubtator.get_review_index_summary",
        title="Get Review Index Summary",
        output_schema=ReviewIndexSummaryResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_review_index_summary(review_id: str) -> dict[str, Any]:
        """Use this to inspect one persisted review index summary without loading passage samples. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""

        async def call() -> dict[str, Any]:
            service = await get_review_index_lifecycle_service()
            return await get_review_index_summary_impl(service=service, review_id=review_id)

        return await run_mcp_tool("pubtator.get_review_index_summary", call)

    @mcp.tool(
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
        """Use this to store a user-supplied GRADE-style evidence certainty judgment linked to prepared passage IDs. The backend stores the judgment; it does not compute certainty. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""

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

    @mcp.tool(
        name="pubtator.list_evidence_certainty",
        title="List Evidence Certainty",
        output_schema=ListEvidenceCertaintyResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def list_evidence_certainty(review_id: str) -> dict[str, Any]:
        """Use this to list user-supplied evidence certainty judgments for a review. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""

        async def call() -> dict[str, Any]:
            service = await get_review_evidence_certainty_service()
            return await list_evidence_certainty_impl(service=service, review_id=review_id)

        return await run_mcp_tool("pubtator.list_evidence_certainty", call)

    @mcp.tool(
        name="pubtator.get_evidence_certainty",
        title="Get Evidence Certainty",
        output_schema=EvidenceCertaintyResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_evidence_certainty(review_id: str, certainty_id: str) -> dict[str, Any]:
        """Use this to retrieve one user-supplied evidence certainty judgment. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""

        async def call() -> dict[str, Any]:
            service = await get_review_evidence_certainty_service()
            return await get_evidence_certainty_impl(
                service=service,
                review_id=review_id,
                certainty_id=certainty_id,
            )

        return await run_mcp_tool("pubtator.get_evidence_certainty", call)

    @mcp.tool(
        name="pubtator.preflight_review_sources",
        title="Preflight Review Sources",
        output_schema=PreflightReviewSourcesResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def preflight_review_sources(
        pmids: list[str],
    ) -> dict[str, Any]:
        """Use this before indexing review evidence to estimate PMID source coverage, PMC fallback availability, and likely full-text versus abstract-only retrieval. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""

        async def call() -> dict[str, Any]:
            service = await get_source_preflight_service()
            return await preflight_review_sources_impl(service=service, pmids=pmids)

        return await run_mcp_tool("pubtator.preflight_review_sources", call, pmids=pmids)

    @mcp.tool(
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
        """Use this after search planning to stage candidate PMIDs with coverage hints and queued review preparation. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""

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

    @mcp.tool(
        name="pubtator.get_research_session_status",
        title="Get Research Session Status",
        output_schema=ResearchSessionStatusResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_research_session_status(review_id: str, session_id: str) -> dict[str, Any]:
        """Use this to poll staged candidate, coverage, and preparation status for a research session. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""

        async def call() -> dict[str, Any]:
            service = await get_research_session_service()
            return await get_research_session_status_impl(
                service=service,
                review_id=review_id,
                session_id=session_id,
            )

        return await run_mcp_tool("pubtator.get_research_session_status", call)

    @mcp.tool(
        name="pubtator.list_research_sessions",
        title="List Research Sessions",
        output_schema=ListResearchSessionsResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def list_research_sessions(review_id: str) -> dict[str, Any]:
        """Use this to list staged research sessions for one review ID. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""

        async def call() -> dict[str, Any]:
            service = await get_research_session_service()
            return await list_research_sessions_impl(service=service, review_id=review_id)

        return await run_mcp_tool("pubtator.list_research_sessions", call)

    @mcp.tool(
        name="pubtator.index_review_evidence",
        title="Index Review Evidence",
        output_schema=IndexReviewEvidenceResponse.model_json_schema(),
        annotations=REVIEW_WRITE_ANNOTATIONS,
    )
    async def index_review_evidence(
        review_id: Annotated[str, Field(min_length=1)],
        pmids: list[str] | None = None,
        curated_urls: list[str] | None = None,
        session_id: str | None = None,
        wait_for_completion: bool = False,
        wait_for_status: Literal["complete", "complete_or_partial", "terminal"] | None = None,
        timeout_ms: int = 0,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Use this when a review needs review-scoped evidence preparation for a review_id and PMIDs/curated URLs. Call this before retrieve_review_context, use session_id to scope staged research sessions, set wait_for_completion for small corpora, and inspect preparation_status before retrieval."""

        async def call() -> dict[str, Any]:
            queue = await get_review_queue()
            return await index_review_evidence_impl(
                queue=queue,
                review_id=review_id,
                pmids=pmids,
                curated_urls=curated_urls,
                session_id=session_id,
                wait_for_completion=wait_for_completion,
                wait_for_status=wait_for_status,
                timeout_ms=timeout_ms,
                dry_run=dry_run,
            )

        return await run_mcp_tool(
            "pubtator.index_review_evidence",
            call,
            pmids=pmids or [],
        )

    @mcp.tool(
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
        """Use this when a user needs to inspect indexed PMIDs, sections, passage counts, and failures for a review_id, including source coverage. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""

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

    @mcp.tool(
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
        """Use this to retrieve exact prepared review passages by stable passage IDs from prior context packs or audit bundles. This only reads the review index and does not call upstream APIs. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""

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

    @mcp.tool(
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
        """Use this to retrieve prepared review passages near a cited stable passage ID for local context expansion. This only reads the review index and does not call upstream APIs. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""

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

    @mcp.tool(
        name="pubtator.export_review_audit_bundle",
        title="Export Review Audit Bundle",
        output_schema=McpReviewAuditBundleResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def export_review_audit_bundle(
        review_id: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Use this to export review preparation status, source coverage, resolver attempts, retrieval runs, passage IDs, and stable citation keys for scientific auditability. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""

        async def call() -> dict[str, Any]:
            service = await get_review_audit_service()
            return await export_review_audit_bundle_impl(
                service=service,
                review_id=review_id,
                session_id=session_id,
            )

        return await run_mcp_tool("pubtator.export_review_audit_bundle", call)

    @mcp.tool(
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
        allow_truncated_passages: bool = True,
        max_chars_per_passage: int = 2200,
    ) -> dict[str, Any]:
        """Use this when a review needs compact citable context from prepared review passages instead of raw BioC export. Use a short keyword query, PMID filters for paper-specific evidence, and diagnostics for zero-result debugging. If zero passages are returned, simplify the query, inspect the review index, or fall back to fetch_publication_annotations. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""

        async def call() -> dict[str, Any]:
            service = await get_review_context_service()
            return await retrieve_review_context_impl(
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
                allow_truncated_passages=allow_truncated_passages,
                max_chars_per_passage=max_chars_per_passage,
            )

        return await run_mcp_tool("pubtator.retrieve_review_context", call, pmids=pmids)

    @mcp.tool(
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
        max_chars: int = 12000,
        max_response_chars: int = 24000,
        deduplicate_passages: bool = True,
        budget_strategy: BudgetStrategy | None = "query_fair",
        min_passages_per_source: int = 1,
        min_passages_per_pmid: int = 0,
        prioritize_pmids: list[str] | None = None,
        include_diagnostics: bool = True,
        include_tables: bool = False,
        include_references: bool = False,
        table_mode: ReviewTableMode = "preview",
        allow_truncated_passages: bool = True,
        max_chars_per_passage: int = 2200,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Use this when a user wants multiple short review retrieval query variants in one call. Default compact mode uses query_fair budgeting: merged passages plus per-query summaries, a fair first-pass budget across queries before overflow, and next_steps for zero-result queries. Use dry_run to get diagnostics and predicted hit counts without returning passage text. Opt into source_fair or scarcity_first to give each PMID/source first-pass representation before overflow. Use diagnostics for query refinement and full only when per-query passage text is needed. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""

        async def call() -> dict[str, Any]:
            service = await get_review_context_service()
            return await retrieve_review_context_batch_impl(
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
                allow_truncated_passages=allow_truncated_passages,
                max_chars_per_passage=max_chars_per_passage,
                dry_run=dry_run,
            )

        return await run_mcp_tool(
            "pubtator.retrieve_review_context_batch",
            call,
            pmids=pmids,
        )
