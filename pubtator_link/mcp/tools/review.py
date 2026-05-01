from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.api.routes.dependencies import (
    get_review_context_service,
    get_review_queue,
    get_review_audit_service,
    get_source_preflight_service,
)
from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD, REVIEW_WRITE_ANNOTATIONS
from pubtator_link.mcp.service_adapters import (
    get_neighboring_review_passages_impl,
    get_review_passages_by_id_impl,
    export_review_audit_bundle_impl,
    index_review_evidence_impl,
    inspect_review_index_impl,
    preflight_review_sources_impl,
    retrieve_review_context_batch_impl,
    retrieve_review_context_impl,
)
from pubtator_link.models.review_rerag import (
    BudgetStrategy,
    PrepareMode,
    ReviewBatchResponseMode,
    ReviewTableMode,
)


def register_review_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="pubtator.preflight_review_sources",
        title="Preflight Review Sources",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def preflight_review_sources(
        pmids: list[str],
    ) -> dict[str, Any]:
        """Use this before indexing review evidence to estimate PMID source coverage, PMC fallback availability, and likely full-text versus abstract-only retrieval. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_source_preflight_service()
        return await preflight_review_sources_impl(service=service, pmids=pmids)

    @mcp.tool(
        name="pubtator.index_review_evidence",
        title="Index Review Evidence",
        annotations=REVIEW_WRITE_ANNOTATIONS,
    )
    async def index_review_evidence(
        review_id: Annotated[str, Field(min_length=1)],
        pmids: list[str] | None = None,
        curated_urls: list[str] | None = None,
        prepare_mode: PrepareMode = "selected",
    ) -> dict[str, Any]:
        """Use this when a review needs review-scoped evidence preparation for a review_id and PMIDs/curated URLs. Call this before retrieve_review_context, then inspect until preparation_status shows complete, partial, or failed. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        queue = await get_review_queue()
        return await index_review_evidence_impl(
            queue=queue,
            review_id=review_id,
            pmids=pmids,
            curated_urls=curated_urls,
            prepare_mode=prepare_mode,
        )

    @mcp.tool(
        name="pubtator.inspect_review_index",
        title="Inspect Review Index",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def inspect_review_index(
        review_id: str,
        pmids: list[str] | None = None,
        include_passage_samples: bool = False,
        sample_per_pmid: int = 2,
    ) -> dict[str, Any]:
        """Use this when a user needs to inspect indexed PMIDs, sections, passage counts, and failures for a review_id, including source coverage. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_review_context_service()
        return await inspect_review_index_impl(
            service=service,
            review_id=review_id,
            pmids=pmids,
            include_passage_samples=include_passage_samples,
            sample_per_pmid=sample_per_pmid,
        )

    @mcp.tool(
        name="pubtator.get_review_passages_by_id",
        title="Get Review Passages By ID",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_review_passages_by_id(
        review_id: str,
        passage_ids: list[str],
        max_chars_per_passage: int = 2200,
    ) -> dict[str, Any]:
        """Use this to retrieve exact prepared review passages by stable passage IDs from prior context packs or audit bundles. This only reads the review index and does not call upstream APIs. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_review_context_service()
        return await get_review_passages_by_id_impl(
            service=service,
            review_id=review_id,
            passage_ids=passage_ids,
            max_chars_per_passage=max_chars_per_passage,
        )

    @mcp.tool(
        name="pubtator.get_neighboring_review_passages",
        title="Get Neighboring Review Passages",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_neighboring_review_passages(
        review_id: str,
        passage_id: str,
        before: int = 1,
        after: int = 1,
        same_section: bool = True,
        max_chars_per_passage: int = 2200,
    ) -> dict[str, Any]:
        """Use this to retrieve prepared review passages near a cited stable passage ID for local context expansion. This only reads the review index and does not call upstream APIs. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_review_context_service()
        return await get_neighboring_review_passages_impl(
            service=service,
            review_id=review_id,
            passage_id=passage_id,
            before=before,
            after=after,
            same_section=same_section,
            max_chars_per_passage=max_chars_per_passage,
        )

    @mcp.tool(
        name="pubtator.export_review_audit_bundle",
        title="Export Review Audit Bundle",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def export_review_audit_bundle(review_id: str) -> dict[str, Any]:
        """Use this to export review preparation status, source coverage, resolver attempts, retrieval runs, passage IDs, and stable citation keys for scientific auditability. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_review_audit_service()
        return await export_review_audit_bundle_impl(service=service, review_id=review_id)

    @mcp.tool(
        name="pubtator.retrieve_review_context",
        title="Retrieve Review Context",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def retrieve_review_context(
        review_id: str,
        question: str,
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
        service = await get_review_context_service()
        return await retrieve_review_context_impl(
            service=service,
            review_id=review_id,
            question=question,
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

    @mcp.tool(
        name="pubtator.retrieve_review_context_batch",
        title="Retrieve Review Context Batch",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def retrieve_review_context_batch(
        review_id: str,
        queries: list[str],
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
        include_diagnostics: bool = True,
        include_tables: bool = False,
        include_references: bool = False,
        table_mode: ReviewTableMode = "preview",
        allow_truncated_passages: bool = True,
        max_chars_per_passage: int = 2200,
    ) -> dict[str, Any]:
        """Use this when a user wants multiple short review retrieval query variants in one call. Default compact mode uses query_fair budgeting: merged passages plus per-query summaries, a fair first-pass budget across queries before overflow, and next_steps for zero-result queries. Opt into source_fair or scarcity_first to give each PMID/source first-pass representation before overflow. Use diagnostics for query refinement and full only when per-query passage text is needed. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_review_context_service()
        return await retrieve_review_context_batch_impl(
            service=service,
            review_id=review_id,
            queries=queries,
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
            include_diagnostics=include_diagnostics,
            include_tables=include_tables,
            include_references=include_references,
            table_mode=table_mode,
            allow_truncated_passages=allow_truncated_passages,
            max_chars_per_passage=max_chars_per_passage,
        )
