"""Service for retrieving review-scoped context passages."""

import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol

from pubtator_link.models.review_rerag import (
    ContextBudget,
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
    RetrieveReviewDiagnostics,
    ReviewIndexTotals,
    ReviewPassageRow,
    ReviewSourceSummary,
    QueryDiagnosticsSummary,
    estimate_tokens_from_chars,
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


SECTION_PRIORITY = {
    "title": 0,
    "abstract": 1,
    "abstr": 1,
    "summary": 2,
    "introduction": 3,
    "intro": 3,
    "background": 4,
    "methods": 5,
    "method": 5,
    "materials and methods": 5,
    "results": 6,
    "result": 6,
    "discussion": 7,
    "discuss": 7,
    "conclusion": 8,
    "conclusions": 8,
    "concl": 8,
    "table": 9,
    "body": 10,
    "ref": 50,
    "references": 50,
}

SOURCE_PRIORITY = {
    "pubtator_full_bioc": 0,
    "pmc_bioc": 1,
    "europe_pmc_jats": 2,
    "curated_pdf": 3,
    "curated_html": 4,
    "docling_pdf": 5,
    "pubtator_abstract": 6,
}


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
        sorted_candidates = sorted(candidates, key=self._rerank_key)
        selected = self._pack_passages(sorted_candidates, request)
        passages = [
            ContextPassage(
                citation_key=f"S{index}",
                passage_id=row.passage_id,
                pmid=row.pmid,
                pmcid=row.pmcid,
                section=row.section,
                text=row.text,
                source_kind=row.source_kind,
                char_count=len(row.text),
                start_char=0,
                end_char=len(row.text),
                boundary="full_passage",
            )
            for index, row in enumerate(selected, start=1)
        ]
        citation_map = {passage.citation_key: passage.passage_id for passage in passages}
        text_chars, estimated_tokens = self._pack_totals(passages)
        budget = self._context_budget(
            max_chars=request.max_chars,
            text_chars=text_chars,
            dropped_count=max(0, len(candidates) - len(selected)),
        )
        diagnostics = None
        if not passages or request.include_diagnostics:
            diagnostics = await self._diagnostics(
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
        query_summaries: list[QueryDiagnosticsSummary] = []
        merged_passages: list[ContextPassage] = []
        dropped: list[ContextDropReason] = []
        seen_passage_ids: set[str] = set()
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
            if request.response_mode == "full":
                results.append(result)

            returned_for_query = 0
            dropped_for_query = 0
            if request.response_mode != "diagnostics":
                for passage in result.context_pack.passages:
                    if request.deduplicate_passages and passage.passage_id in seen_passage_ids:
                        dropped_for_query += 1
                        dropped.append(
                            ContextDropReason(
                                reason="duplicate_passage",
                                passage_id=passage.passage_id,
                                pmid=passage.pmid,
                                section=passage.section,
                                char_count=len(passage.text),
                            )
                        )
                        continue
                    if len(merged_passages) >= request.max_total_passages:
                        dropped_for_query += 1
                        dropped.append(
                            ContextDropReason(
                                reason="max_total_passages_exceeded",
                                passage_id=passage.passage_id,
                                pmid=passage.pmid,
                                section=passage.section,
                                char_count=len(passage.text),
                            )
                        )
                        break
                    if total_chars + len(passage.text) > request.max_chars:
                        dropped_for_query += 1
                        dropped.append(
                            ContextDropReason(
                                reason="char_budget_exceeded",
                                passage_id=passage.passage_id,
                                pmid=passage.pmid,
                                section=passage.section,
                                char_count=len(passage.text),
                            )
                        )
                        continue
                    seen_passage_ids.add(passage.passage_id)
                    merged_passages.append(
                        passage.model_copy(
                            update={
                                "citation_key": f"S{len(merged_passages) + 1}",
                                "char_count": len(passage.text),
                            }
                        )
                    )
                    total_chars += len(passage.text)
                    returned_for_query += 1

            query_summaries.append(
                self._query_summary(
                    query=query,
                    result=result,
                    returned_count=returned_for_query,
                    dropped_count=dropped_for_query,
                )
            )

        citation_map = {passage.citation_key: passage.passage_id for passage in merged_passages}
        text_chars, estimated_tokens = self._pack_totals(merged_passages)
        budget = self._context_budget(
            max_chars=request.max_chars,
            text_chars=text_chars,
            dropped_count=len(dropped),
        )
        return RetrieveReviewContextBatchResponse(
            review_id=review_id,
            response_mode=request.response_mode,
            results=results,
            query_summaries=query_summaries,
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

    def _pack_passages(
        self,
        candidates: list[ReviewPassageRow],
        request: RetrieveReviewContextRequest,
    ) -> list[ReviewPassageRow]:
        selected: list[ReviewPassageRow] = []
        pmid_counts: dict[str, int] = defaultdict(int)
        total_chars = 0
        enforce_pmid_diversity = len(request.pmids) != 1

        for row in candidates:
            if len(selected) >= request.max_passages:
                break
            if (
                enforce_pmid_diversity
                and row.pmid is not None
                and pmid_counts[row.pmid] >= request.max_passages_per_pmid
            ):
                continue
            if total_chars + len(row.text) > request.max_chars:
                continue

            selected.append(row)
            total_chars += len(row.text)
            if row.pmid is not None:
                pmid_counts[row.pmid] += 1

        return selected

    @staticmethod
    def _context_budget(max_chars: int, text_chars: int, dropped_count: int = 0) -> ContextBudget:
        estimated_json_chars = 1200 + int(text_chars * 0.25)
        estimated_total_chars = text_chars + estimated_json_chars
        return ContextBudget(
            max_chars=max_chars,
            text_chars=text_chars,
            estimated_json_chars=estimated_json_chars,
            estimated_total_chars=estimated_total_chars,
            estimated_tokens=estimate_tokens_from_chars(estimated_total_chars),
            dropped_count=dropped_count,
        )

    @staticmethod
    def _pack_totals(passages: Sequence[ContextPassage]) -> tuple[int, int]:
        text_chars = sum(len(passage.text) for passage in passages)
        return text_chars, estimate_tokens_from_chars(text_chars)

    def _query_summary(
        self,
        *,
        query: str,
        result: RetrieveReviewContextResponse,
        returned_count: int,
        dropped_count: int,
    ) -> QueryDiagnosticsSummary:
        passages = result.context_pack.passages
        diagnostics = result.diagnostics
        top_sections = list(dict.fromkeys(passage.section for passage in passages))[:5]
        top_pmids = [
            pmid
            for pmid in dict.fromkeys(passage.pmid for passage in passages)
            if pmid is not None
        ][:10]
        candidate_count = diagnostics.candidate_count if diagnostics else len(passages)
        selected_count = diagnostics.selected_count if diagnostics else len(passages)
        suggested_queries = diagnostics.suggested_queries if diagnostics else []
        query_tokens = diagnostics.query_tokens if diagnostics else self._query_tokens(query)
        zero_result_reason = None
        if returned_count == 0:
            zero_result_reason = "no_candidate_matches"
            if result.preparation_status.total == 0:
                zero_result_reason = "review_not_indexed"
            elif result.preparation_status.failed and not candidate_count:
                zero_result_reason = "preparation_failed"
            elif candidate_count and dropped_count:
                zero_result_reason = "all_candidates_over_budget"
        return QueryDiagnosticsSummary(
            query=query,
            query_tokens=query_tokens,
            candidate_count=candidate_count,
            selected_count=selected_count,
            returned_count=returned_count,
            dropped_count=dropped_count,
            top_sections=top_sections,
            top_pmids=top_pmids,
            zero_result_reason=zero_result_reason,
            suggested_queries=suggested_queries,
        )

    async def _preparation_status(self, review_id: str) -> PreparationStatus:
        status = await self.repository.preparation_status(review_id)
        if isinstance(status, PreparationStatus):
            return status
        return PreparationStatus(**status)

    async def _diagnostics(
        self,
        *,
        review_id: str,
        request: RetrieveReviewContextRequest,
        candidate_count: int,
        selected_count: int,
    ) -> RetrieveReviewDiagnostics:
        query_tokens = self._query_tokens(request.question)
        available_sections = await self.repository.available_sections(review_id)
        indexed_pmids = await self.repository.indexed_pmids(review_id)
        failed_sources = await self.repository.list_review_failed_sources(review_id)
        section_label = ", ".join(available_sections) if available_sections else "none"
        message = (
            f"No passages selected. Review {review_id} has {len(indexed_pmids)} indexed PMIDs "
            f"and sections {section_label}. Try shorter keyword queries or remove section filters."
            if selected_count == 0
            else f"Selected {selected_count} passages from {candidate_count} candidates."
        )
        return RetrieveReviewDiagnostics(
            query=request.question,
            query_tokens=query_tokens,
            candidate_count=candidate_count,
            selected_count=selected_count,
            available_sections=available_sections,
            indexed_pmids=indexed_pmids,
            failed_sources=failed_sources,
            filter_summary={
                "pmids": list(request.pmids),
                "entity_ids": list(request.entity_ids),
                "sections": list(request.sections),
            },
            suggested_queries=self._suggested_queries(query_tokens, available_sections),
            message=message,
        )

    @staticmethod
    def _query_tokens(query: str) -> list[str]:
        tokens: list[str] = []
        seen: set[str] = set()
        for token in re.findall(r"[a-zA-Z0-9]+", query.lower()):
            if len(token) < 3 or token in seen:
                continue
            seen.add(token)
            tokens.append(token)
            if len(tokens) >= 12:
                break
        return tokens

    @staticmethod
    def _suggested_queries(tokens: list[str], available_sections: Sequence[str]) -> list[str]:
        section_tokens = {
            token
            for section in available_sections
            for token in re.findall(r"[a-zA-Z0-9]+", section.lower())
        }
        filtered = [token for token in tokens if token not in section_tokens]
        suggestions: list[str] = []
        for size in (3, 5):
            if len(filtered) >= size:
                suggestions.append(" ".join(filtered[:size]))
        if len(filtered) >= 2:
            suggestions.append(" ".join(filtered[:2]))
        if not suggestions and filtered:
            suggestions.append(" ".join(filtered))
        deduped: list[str] = []
        for suggestion in suggestions:
            if suggestion and suggestion not in deduped:
                deduped.append(suggestion)
        return deduped[:3]

    @staticmethod
    def _rerank_key(row: ReviewPassageRow) -> tuple[float, int, int, str, str]:
        return (
            -row.lexical_rank,
            SECTION_PRIORITY.get(row.section.strip().lower(), 100),
            SOURCE_PRIORITY.get(row.source_kind, 100),
            row.pmid or "",
            row.passage_id,
        )
