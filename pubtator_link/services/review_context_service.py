"""Service for retrieving review-scoped context passages."""

from collections.abc import Sequence
from typing import Protocol

from pubtator_link.models.review_rerag import (
    ContextPack,
    FailedSourceSummary,
    InspectReviewIndexRequest,
    InspectReviewIndexResponse,
    PreparationStatus,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextBatchResponse,
    RetrieveReviewContextRequest,
    RetrieveReviewContextResponse,
    ReviewIndexTotals,
    ReviewPassageRow,
    ReviewSourceSummary,
    SourceCoverage,
)
from pubtator_link.services.review_context.batch_budgeting import merge_batch_context
from pubtator_link.services.review_context.diagnostics import (
    build_diagnostics,
)
from pubtator_link.services.review_context.packing import (
    context_budget,
    context_passage_from_row,
    pack_passages,
    pack_totals,
)
from pubtator_link.services.review_context.ranking import (
    SOURCE_COVERAGE_SCARCITY_PRIORITY,
    rerank_key,
)


class ReviewContextRepository(Protocol):
    """Repository interface needed by ReviewContextService."""

    async def search_passages(
        self,
        review_id: str,
        query: str,
        *,
        entity_ids: Sequence[str] | None = None,
        pmids: Sequence[str] | None = None,
        sections: Sequence[str] | None = None,
        limit: int = 8,
    ) -> list[ReviewPassageRow]:
        """Return candidate passages for a review-scoped retrieval request."""

    async def preparation_status(self, review_id: str) -> PreparationStatus | dict[str, int]:
        """Return preparation status counts for a review."""

    async def list_review_sources(
        self,
        review_id: str,
        pmids: Sequence[str] | None = None,
        *,
        include_passage_samples: bool = False,
        sample_per_pmid: int = 2,
    ) -> list[ReviewSourceSummary]:
        """Return index source summaries for a review."""

    async def list_review_failed_sources(self, review_id: str) -> list[FailedSourceSummary]:
        """Return failed source summaries for a review."""

    async def review_index_totals(self, review_id: str) -> ReviewIndexTotals:
        """Return aggregate index totals for a review."""

    async def available_sections(self, review_id: str) -> list[str]:
        """Return indexed section names for diagnostics."""

    async def indexed_pmids(self, review_id: str) -> list[str]:
        """Return indexed PMIDs for diagnostics."""


class ReviewContextService:
    """Retrieve, rerank, and pack review-scoped context passages."""

    def __init__(self, repository: ReviewContextRepository) -> None:
        self.repository = repository

    async def retrieve_context(
        self,
        review_id: str,
        request: RetrieveReviewContextRequest,
    ) -> RetrieveReviewContextResponse:
        """Build a citable context pack for a review question."""
        candidates = await self.repository.search_passages(
            review_id,
            request.question,
            entity_ids=request.entity_ids,
            pmids=request.pmids,
            sections=request.sections,
            limit=80,
        )
        sorted_candidates = sorted(candidates, key=rerank_key)
        packed = pack_passages(sorted_candidates, request)
        selected = packed.selected
        dropped = packed.dropped
        passages = [
            context_passage_from_row(index=index, row=row, request=request)
            for index, row in enumerate(selected, start=1)
        ]
        citation_map = {passage.citation_key: passage.passage_id for passage in passages}
        text_chars, estimated_tokens = pack_totals(passages)
        budget = context_budget(
            max_chars=request.max_chars,
            text_chars=text_chars,
            dropped_count=len(dropped),
        )
        diagnostics = None
        if not passages or request.include_diagnostics:
            diagnostics = await build_diagnostics(
                repository=self.repository,
                review_id=review_id,
                request=request,
                candidate_count=len(candidates),
                selected_count=len(selected),
            )
        return RetrieveReviewContextResponse(
            review_id=review_id,
            context_pack=ContextPack(
                question=request.question,
                passages=passages,
                citation_map=citation_map,
                total_chars=text_chars,
                estimated_tokens=estimated_tokens,
                budget=budget,
                dropped=dropped,
            ),
            preparation_status=await self._preparation_status(review_id),
            diagnostics=diagnostics,
        )

    async def retrieve_context_batch(
        self,
        review_id: str,
        request: RetrieveReviewContextBatchRequest,
    ) -> RetrieveReviewContextBatchResponse:
        """Retrieve multiple query variants and merge selected passages."""
        results: list[RetrieveReviewContextResponse] = []
        query_results: list[RetrieveReviewContextResponse] = []

        for query in request.queries:
            result = await self.retrieve_context(
                review_id,
                RetrieveReviewContextRequest(
                    question=query,
                    pmids=request.pmids,
                    entity_ids=request.entity_ids,
                    sections=request.sections,
                    max_passages=request.max_passages_per_query,
                    max_chars=request.max_chars,
                    include_diagnostics=request.include_diagnostics
                    or request.response_mode == "diagnostics",
                    include_tables=request.include_tables,
                    include_references=request.include_references,
                    table_mode=request.table_mode,
                    allow_truncated_passages=request.allow_truncated_passages,
                    max_chars_per_passage=request.max_chars_per_passage,
                ),
            )
            query_results.append(result)
            if request.response_mode == "full":
                results.append(result)

        coverage_by_source = {}
        if request.budget_strategy != "query_fair":
            coverage_by_source = await self._source_coverage_by_key(review_id)
        merged = merge_batch_context(
            request=request,
            query_results=query_results,
            coverage_by_source=coverage_by_source,
        )
        citation_map = {passage.citation_key: passage.passage_id for passage in merged.passages}
        budget = context_budget(
            max_chars=request.max_chars,
            text_chars=merged.budget_text_chars,
            dropped_count=len(merged.dropped),
        )
        return RetrieveReviewContextBatchResponse(
            review_id=review_id,
            response_mode=request.response_mode,
            results=results,
            query_summaries=merged.query_summaries,
            source_budget_summaries=merged.source_budget_summaries,
            merged_context_pack=ContextPack(
                question="\n".join(request.queries),
                passages=merged.passages,
                citation_map=citation_map,
                total_chars=merged.text_chars,
                estimated_tokens=merged.estimated_tokens,
                budget=budget,
                dropped=merged.dropped,
            ),
            preparation_status=await self._preparation_status(review_id),
            budget=budget,
        )

    async def inspect_review_index(
        self,
        review_id: str,
        request: InspectReviewIndexRequest,
    ) -> InspectReviewIndexResponse:
        """Inspect prepared sources, aggregate counts, and failed sources."""
        preparation_status = await self._preparation_status(review_id)
        sources = await self.repository.list_review_sources(
            review_id,
            request.pmids,
            include_passage_samples=request.include_passage_samples,
            sample_per_pmid=request.sample_per_pmid,
        )
        totals = await self.repository.review_index_totals(review_id)
        failed_sources = await self.repository.list_review_failed_sources(review_id)
        return InspectReviewIndexResponse(
            review_id=review_id,
            preparation_status=preparation_status,
            sources=sources,
            totals=totals,
            failed_sources=failed_sources,
        )

    async def _source_coverage_by_key(self, review_id: str) -> dict[str, SourceCoverage]:
        sources = await self.repository.list_review_sources(
            review_id,
            pmids=None,
            include_passage_samples=False,
            sample_per_pmid=0,
        )
        coverage_by_key: dict[str, SourceCoverage] = {}
        for source in sources:
            source_keys = [source.source_id]
            if source.pmid is not None:
                source_keys.append(source.pmid)
            for source_key in source_keys:
                existing = coverage_by_key.get(source_key)
                if existing is None or SOURCE_COVERAGE_SCARCITY_PRIORITY.get(
                    source.coverage, SOURCE_COVERAGE_SCARCITY_PRIORITY["unknown"]
                ) < SOURCE_COVERAGE_SCARCITY_PRIORITY.get(
                    existing, SOURCE_COVERAGE_SCARCITY_PRIORITY["unknown"]
                ):
                    coverage_by_key[source_key] = source.coverage
        return coverage_by_key

    async def _preparation_status(self, review_id: str) -> PreparationStatus:
        status = await self.repository.preparation_status(review_id)
        if isinstance(status, PreparationStatus):
            return status
        return PreparationStatus(**status)
