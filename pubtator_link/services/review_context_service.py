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
    QueryDiagnosticsSummary,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextBatchResponse,
    RetrieveReviewContextRequest,
    RetrieveReviewContextResponse,
    RetrieveReviewDiagnostics,
    ReviewIndexTotals,
    ReviewPassageRow,
    ReviewSourceSummary,
    SourceBudgetSummary,
    SourceCoverage,
    ZeroResultReason,
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

SOURCE_COVERAGE_SCARCITY_PRIORITY = {
    "title_only": 0,
    "abstract_only": 1,
    "curated_url": 2,
    "full_text": 3,
    "unknown": 4,
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
        selected, dropped = self._pack_passages(sorted_candidates, request)
        passages = [
            self._context_passage_from_row(index=index, row=row, request=request)
            for index, row in enumerate(selected, start=1)
        ]
        citation_map = {passage.citation_key: passage.passage_id for passage in passages}
        text_chars, estimated_tokens = self._pack_totals(passages)
        budget = self._context_budget(
            max_chars=request.max_chars,
            text_chars=text_chars,
            dropped_count=len(dropped),
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
            return passage.pmid

        def ensure_source_budget_summary(
            source_key: str | None,
            coverage: SourceCoverage = "unknown",
        ) -> SourceBudgetSummary:
            summary = source_budget_stats.get(source_key)
            if summary is None:
                summary = SourceBudgetSummary(pmid=source_key, coverage=coverage)
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
                next_budget = self._context_budget(
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
                coverage_by_pmid = await self._source_coverage_by_pmid(review_id)
                candidates: list[tuple[int, int, ContextPassage]] = []
                returned_by_source: dict[str | None, int] = defaultdict(int)
                quota_deferred_candidates: set[tuple[int, int]] = set()

                def coverage_for_passage(passage: ContextPassage) -> SourceCoverage:
                    if passage.pmid is None:
                        return "unknown"
                    return coverage_by_pmid.get(passage.pmid, "unknown")

                for query_index, result in enumerate(query_results):
                    for passage_index, passage in enumerate(result.context_pack.passages):
                        source_key = source_key_for_passage(passage)
                        coverage = coverage_for_passage(passage)
                        summary = ensure_source_budget_summary(source_key, coverage)
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
                self._query_summary(
                    query=request.queries[query_index],
                    result=result,
                    returned_count=returned_counts[query_index],
                    dropped_count=dropped_counts[query_index],
                )
            )

        citation_map = {passage.citation_key: passage.passage_id for passage in merged_passages}
        text_chars, estimated_tokens = self._pack_totals(merged_passages)
        budget_text_chars = text_chars
        if request.response_mode == "full":
            budget_text_chars += sum(
                result.context_pack.total_chars
                or sum(len(passage.text) for passage in result.context_pack.passages)
                for result in results
            )
        budget = self._context_budget(
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

    async def _source_coverage_by_pmid(self, review_id: str) -> dict[str, SourceCoverage]:
        sources = await self.repository.list_review_sources(
            review_id,
            pmids=None,
            include_passage_samples=False,
            sample_per_pmid=0,
        )
        coverage_by_pmid: dict[str, SourceCoverage] = {}
        for source in sources:
            if source.pmid is None:
                continue
            existing = coverage_by_pmid.get(source.pmid)
            if existing is None or SOURCE_COVERAGE_SCARCITY_PRIORITY.get(
                source.coverage, SOURCE_COVERAGE_SCARCITY_PRIORITY["unknown"]
            ) < SOURCE_COVERAGE_SCARCITY_PRIORITY.get(
                existing, SOURCE_COVERAGE_SCARCITY_PRIORITY["unknown"]
            ):
                coverage_by_pmid[source.pmid] = source.coverage
        return coverage_by_pmid

    def _pack_passages(
        self,
        candidates: list[ReviewPassageRow],
        request: RetrieveReviewContextRequest,
    ) -> tuple[list[ReviewPassageRow], list[ContextDropReason]]:
        selected: list[ReviewPassageRow] = []
        dropped: list[ContextDropReason] = []
        pmid_counts: dict[str, int] = defaultdict(int)
        total_chars = 0
        enforce_pmid_diversity = len(request.pmids) != 1

        for row in candidates:
            if len(selected) >= request.max_passages:
                break
            if not self._section_allowed(row, request):
                continue
            if (
                enforce_pmid_diversity
                and row.pmid is not None
                and pmid_counts[row.pmid] >= request.max_passages_per_pmid
            ):
                continue
            effective_len = self._effective_passage_len(row, request)
            if effective_len is None:
                dropped.append(
                    ContextDropReason(
                        reason="passage_over_max_chars_per_passage",
                        passage_id=row.passage_id,
                        pmid=row.pmid,
                        section=row.section,
                        char_count=len(row.text),
                    )
                )
                continue
            if total_chars + effective_len > request.max_chars:
                dropped.append(
                    ContextDropReason(
                        reason="char_budget_exceeded",
                        passage_id=row.passage_id,
                        pmid=row.pmid,
                        section=row.section,
                        char_count=effective_len,
                    )
                )
                continue

            selected.append(row)
            total_chars += effective_len
            if row.pmid is not None:
                pmid_counts[row.pmid] += 1

        return selected, dropped

    def _context_passage_from_row(
        self,
        *,
        index: int,
        row: ReviewPassageRow,
        request: RetrieveReviewContextRequest,
    ) -> ContextPassage:
        text, start_char, end_char, truncated = self._excerpt_text(
            row.text,
            query_tokens=self._query_tokens(request.question),
            max_chars=request.max_chars_per_passage,
            allow_truncated=request.allow_truncated_passages,
        )
        return ContextPassage(
            citation_key=f"S{index}",
            passage_id=row.passage_id,
            pmid=row.pmid,
            pmcid=row.pmcid,
            section=row.section,
            text=text,
            source_kind=row.source_kind,
            char_count=len(text),
            truncated=truncated,
            start_char=start_char,
            end_char=end_char,
            boundary="query_window" if truncated else "full_passage",
        )

    def _effective_passage_len(
        self, row: ReviewPassageRow, request: RetrieveReviewContextRequest
    ) -> int | None:
        if len(row.text) <= request.max_chars_per_passage:
            return len(row.text)
        if not request.allow_truncated_passages:
            return None
        return request.max_chars_per_passage

    @staticmethod
    def _is_table_section(section: str) -> bool:
        return "table" in section.strip().lower()

    @staticmethod
    def _is_reference_section(section: str) -> bool:
        lowered = section.strip().lower()
        return lowered in {"ref", "refs", "reference", "references", "bibliography"} or (
            "reference" in lowered
        )

    def _section_allowed(
        self, row: ReviewPassageRow, request: RetrieveReviewContextRequest
    ) -> bool:
        if self._is_reference_section(row.section) and not request.include_references:
            return False
        if self._is_table_section(row.section):
            return request.include_tables or request.table_mode == "full"
        return True

    @staticmethod
    def _excerpt_text(
        text: str,
        *,
        query_tokens: Sequence[str],
        max_chars: int,
        allow_truncated: bool,
    ) -> tuple[str, int, int, bool]:
        if len(text) <= max_chars or not allow_truncated:
            return text, 0, len(text), False

        lowered = text.lower()
        match_index = -1
        for token in query_tokens:
            match_index = lowered.find(token.lower())
            if match_index >= 0:
                break
        if match_index < 0:
            match_index = 0

        half_window = max_chars // 2
        start = max(0, match_index - half_window)
        end = min(len(text), start + max_chars)
        start = max(0, end - max_chars)
        return text[start:end], start, end, True

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
            pmid for pmid in dict.fromkeys(passage.pmid for passage in passages) if pmid is not None
        ][:10]
        candidate_count = diagnostics.candidate_count if diagnostics else len(passages)
        selected_count = diagnostics.selected_count if diagnostics else len(passages)
        suggested_queries = diagnostics.suggested_queries if diagnostics else []
        query_tokens = diagnostics.query_tokens if diagnostics else self._query_tokens(query)
        zero_result_reason: ZeroResultReason | None = None
        next_steps: list[str] = []
        if returned_count == 0:
            zero_result_reason = "no_candidate_matches"
            if result.preparation_status.total == 0:
                zero_result_reason = "review_not_indexed"
                next_steps = ["index_review_evidence", "inspect_review_index"]
            elif result.preparation_status.failed and not candidate_count:
                zero_result_reason = "preparation_failed"
                next_steps = ["inspect_review_index", "retry_failed_pmids"]
            elif candidate_count and dropped_count:
                zero_result_reason = "all_candidates_over_budget"
                next_steps = ["increase_budget", "lower_max_passages_per_query"]
            else:
                next_steps = ["shorten_query", "drop_filters", "inspect_review_index"]
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
            next_steps=next_steps,
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
