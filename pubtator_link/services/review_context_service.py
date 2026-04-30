"""Service for retrieving review-scoped context passages."""

from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol

from pubtator_link.models.review_rerag import (
    ContextDropReason,
    ContextPack,
    ContextPassage,
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
    SourceBudgetSummary,
    SourceCoverage,
)
from pubtator_link.services.review_context.diagnostics import (
    build_diagnostics,
    query_summary,
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
        query_summaries: list[QueryDiagnosticsSummary] = []
        merged_passages: list[ContextPassage] = []
        dropped: list[ContextDropReason] = []
        seen_passage_ids: set[str] = set()
        handled_passages: set[tuple[int, int]] = set()
        returned_counts: list[int] = []
        dropped_counts: list[int] = []
        query_chars: list[int] = []
        source_budget_stats: dict[str | None, SourceBudgetSummary] = {}
        source_budget_order: list[str | None] = []
        total_chars = 0

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

            dropped.extend(result.context_pack.dropped)
            returned_counts.append(0)
            dropped_counts.append(len(result.context_pack.dropped))
            query_chars.append(0)

        def source_key_for_passage(passage: ContextPassage) -> str | None:
            return passage.pmid or passage.source_id

        def ensure_source_budget_summary(
            source_key: str | None,
            passage: ContextPassage | None = None,
            coverage: SourceCoverage = "unknown",
        ) -> SourceBudgetSummary:
            summary = source_budget_stats.get(source_key)
            if summary is None:
                summary = SourceBudgetSummary(
                    source_id=passage.source_id if passage is not None else source_key,
                    pmid=passage.pmid if passage is not None else source_key,
                    coverage=coverage,
                )
                source_budget_stats[source_key] = summary
                source_budget_order.append(source_key)
            elif summary.coverage == "unknown" and coverage != "unknown":
                summary.coverage = coverage
            return summary

        def drop_passage(
            query_index: int,
            passage: ContextPassage,
            reason: str,
            *,
            source_key: str | None = None,
        ) -> None:
            dropped_counts[query_index] += 1
            dropped.append(
                ContextDropReason(
                    reason=reason,
                    passage_id=passage.passage_id,
                    pmid=passage.pmid,
                    section=passage.section,
                    char_count=len(passage.text),
                )
            )
            if source_key in source_budget_stats:
                source_budget_stats[source_key].dropped_count += 1

        def add_passage(
            query_index: int,
            passage: ContextPassage,
            *,
            source_key: str | None = None,
        ) -> None:
            nonlocal total_chars
            seen_passage_ids.add(passage.passage_id)
            merged_passages.append(
                passage.model_copy(
                    update={
                        "citation_key": f"S{len(merged_passages) + 1}",
                        "stable_citation_key": passage.stable_citation_key,
                        "char_count": len(passage.text),
                    }
                )
            )
            passage_len = len(passage.text)
            total_chars += passage_len
            query_chars[query_index] += passage_len
            returned_counts[query_index] += 1
            if source_key in source_budget_stats:
                source_budget_stats[source_key].returned_count += 1

        def try_merge_passage(
            query_index: int,
            passage_index: int,
            passage: ContextPassage,
            *,
            reserve_limit: int | None,
            source_key: str | None = None,
        ) -> bool:
            handled_key = (query_index, passage_index)
            if handled_key in handled_passages:
                return True
            passage_len = len(passage.text)
            if (
                reserve_limit is not None
                and returned_counts[query_index] > 0
                and query_chars[query_index] + passage_len > reserve_limit
            ):
                return False
            handled_passages.add(handled_key)
            if request.deduplicate_passages and passage.passage_id in seen_passage_ids:
                drop_passage(query_index, passage, "duplicate_passage", source_key=source_key)
                return True
            if len(merged_passages) >= request.max_total_passages:
                drop_passage(
                    query_index,
                    passage,
                    "max_total_passages_exceeded",
                    source_key=source_key,
                )
                return True
            if total_chars + passage_len > request.max_chars:
                drop_passage(query_index, passage, "char_budget_exceeded", source_key=source_key)
                return True
            if request.response_mode != "full":
                next_budget = context_budget(
                    max_chars=request.max_chars,
                    text_chars=total_chars + passage_len,
                    dropped_count=len(dropped),
                )
                if next_budget.estimated_total_chars > request.max_response_chars:
                    drop_passage(
                        query_index,
                        passage,
                        "response_char_budget_exceeded",
                        source_key=source_key,
                    )
                    return True
            add_passage(query_index, passage, source_key=source_key)
            return True

        if request.response_mode != "diagnostics":
            if request.budget_strategy == "query_fair":
                reserve_limit = max(1, request.max_chars // len(request.queries))
                for query_index, result in enumerate(query_results):
                    for passage_index, passage in enumerate(result.context_pack.passages):
                        try_merge_passage(
                            query_index,
                            passage_index,
                            passage,
                            reserve_limit=reserve_limit,
                        )
                for query_index, result in enumerate(query_results):
                    for passage_index, passage in enumerate(result.context_pack.passages):
                        try_merge_passage(
                            query_index,
                            passage_index,
                            passage,
                            reserve_limit=None,
                        )
            else:
                coverage_by_source = await self._source_coverage_by_key(review_id)
                candidates: list[tuple[int, int, ContextPassage]] = []
                returned_by_source: dict[str | None, int] = defaultdict(int)
                quota_deferred_candidates: set[tuple[int, int]] = set()

                def coverage_for_passage(passage: ContextPassage) -> SourceCoverage:
                    source_key = source_key_for_passage(passage)
                    if source_key is None:
                        return "unknown"
                    return coverage_by_source.get(source_key, "unknown")

                for query_index, result in enumerate(query_results):
                    for passage_index, passage in enumerate(result.context_pack.passages):
                        source_key = source_key_for_passage(passage)
                        coverage = coverage_for_passage(passage)
                        summary = ensure_source_budget_summary(source_key, passage, coverage)
                        summary.candidate_count += 1
                        candidates.append((query_index, passage_index, passage))

                first_pass_candidates = list(candidates)
                if request.budget_strategy == "scarcity_first":
                    first_pass_candidates.sort(
                        key=lambda candidate: (
                            SOURCE_COVERAGE_SCARCITY_PRIORITY.get(
                                coverage_for_passage(candidate[2]),
                                SOURCE_COVERAGE_SCARCITY_PRIORITY["unknown"],
                            ),
                            candidate[0],
                            candidate[1],
                        )
                    )

                for target_returned_count in range(1, request.min_passages_per_source + 1):
                    for query_index, passage_index, passage in first_pass_candidates:
                        handled_key = (query_index, passage_index)
                        if handled_key in handled_passages:
                            continue
                        source_key = source_key_for_passage(passage)
                        if returned_by_source[source_key] >= target_returned_count:
                            quota_deferred_candidates.add(handled_key)
                            continue
                        source_budget_stats[source_key].first_pass_eligible = True
                        before_count = len(merged_passages)
                        try_merge_passage(
                            query_index,
                            passage_index,
                            passage,
                            reserve_limit=None,
                            source_key=source_key,
                        )
                        if len(merged_passages) > before_count:
                            returned_by_source[source_key] += 1
                for query_index, passage_index, passage in candidates:
                    handled_key = (query_index, passage_index)
                    source_key = source_key_for_passage(passage)
                    if (
                        handled_key not in handled_passages
                        and handled_key in quota_deferred_candidates
                        and returned_by_source[source_key] >= request.min_passages_per_source
                        and len(merged_passages) >= request.max_total_passages
                    ):
                        handled_passages.add(handled_key)
                        drop_passage(
                            query_index,
                            passage,
                            "source_budget_exceeded",
                            source_key=source_key,
                        )
                        continue
                    try_merge_passage(
                        query_index,
                        passage_index,
                        passage,
                        reserve_limit=None,
                        source_key=source_key,
                    )

        for query_index, result in enumerate(query_results):
            query_summaries.append(
                query_summary(
                    query=request.queries[query_index],
                    result=result,
                    returned_count=returned_counts[query_index],
                    dropped_count=dropped_counts[query_index],
                )
            )

        citation_map = {passage.citation_key: passage.passage_id for passage in merged_passages}
        text_chars, estimated_tokens = pack_totals(merged_passages)
        budget_text_chars = text_chars
        if request.response_mode == "full":
            budget_text_chars += sum(
                result.context_pack.total_chars
                or sum(len(passage.text) for passage in result.context_pack.passages)
                for result in results
            )
        budget = context_budget(
            max_chars=request.max_chars,
            text_chars=budget_text_chars,
            dropped_count=len(dropped),
        )
        return RetrieveReviewContextBatchResponse(
            review_id=review_id,
            response_mode=request.response_mode,
            results=results,
            query_summaries=query_summaries,
            source_budget_summaries=[
                source_budget_stats[source_key] for source_key in source_budget_order
            ],
            merged_context_pack=ContextPack(
                question="\n".join(request.queries),
                passages=merged_passages,
                citation_map=citation_map,
                total_chars=text_chars,
                estimated_tokens=estimated_tokens,
                budget=budget,
                dropped=dropped,
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
