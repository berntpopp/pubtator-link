from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from pubtator_link.models.review_rerag import (
    ContextDropReason,
    ContextPassage,
    PmidStatusSummary,
    QueryDiagnosticsSummary,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextResponse,
    SourceBudgetSummary,
    SourceCoverage,
)
from pubtator_link.services.review_context.diagnostics import query_summary
from pubtator_link.services.review_context.packing import context_budget, pack_totals
from pubtator_link.services.review_context.ranking import SOURCE_COVERAGE_SCARCITY_PRIORITY


@dataclass
class MergedBatchContext:
    passages: list[ContextPassage]
    dropped: list[ContextDropReason]
    query_summaries: list[QueryDiagnosticsSummary]
    source_budget_summaries: list[SourceBudgetSummary]
    pmid_status_summary: list[PmidStatusSummary]
    text_chars: int
    estimated_tokens: int
    budget_text_chars: int


def merge_batch_context(
    *,
    request: RetrieveReviewContextBatchRequest,
    query_results: list[RetrieveReviewContextResponse],
    coverage_by_source: dict[str, SourceCoverage],
) -> MergedBatchContext:
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
    pmid_stats: dict[str, PmidStatusSummary] = {}
    pmid_order: list[str] = []
    total_chars = 0
    prioritized_pmids = set(request.prioritize_pmids)

    for result in query_results:
        dropped.extend(result.context_pack.dropped)
        returned_counts.append(0)
        dropped_counts.append(len(result.context_pack.dropped))
        query_chars.append(0)

    def source_key_for_passage(passage: ContextPassage) -> str | None:
        return passage.pmid or passage.source_id

    def ensure_pmid_summary(pmid: str | None) -> PmidStatusSummary | None:
        if pmid is None:
            return None
        summary = pmid_stats.get(pmid)
        if summary is None:
            summary = PmidStatusSummary(pmid=pmid, prioritized=pmid in prioritized_pmids)
            pmid_stats[pmid] = summary
            pmid_order.append(pmid)
        return summary

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
        pmid_summary = ensure_pmid_summary(passage.pmid)
        if pmid_summary is not None:
            pmid_summary.passages_dropped += 1

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
        pmid_summary = ensure_pmid_summary(passage.pmid)
        if pmid_summary is not None:
            pmid_summary.passages_returned += 1

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
        all_candidates: list[tuple[int, int, ContextPassage]] = [
            (query_index, passage_index, passage)
            for query_index, result in enumerate(query_results)
            for passage_index, passage in enumerate(result.context_pack.passages)
        ]
        for _query_index, _passage_index, passage in all_candidates:
            pmid_summary = ensure_pmid_summary(passage.pmid)
            if pmid_summary is not None:
                pmid_summary.candidate_count += 1

        if request.min_passages_per_pmid:
            returned_by_pmid: dict[str, int] = defaultdict(int)

            def pmid_floor_sort_key(candidate: tuple[int, int, ContextPassage]) -> tuple[int, int, int]:
                query_index, passage_index, passage = candidate
                priority_index = (
                    request.prioritize_pmids.index(passage.pmid)
                    if passage.pmid in prioritized_pmids
                    else len(request.prioritize_pmids)
                )
                return priority_index, query_index, passage_index

            for target_returned_count in range(1, request.min_passages_per_pmid + 1):
                for query_index, passage_index, passage in sorted(
                    all_candidates,
                    key=pmid_floor_sort_key,
                ):
                    if passage.pmid is None:
                        continue
                    if returned_by_pmid[passage.pmid] >= target_returned_count:
                        continue
                    before_count = len(merged_passages)
                    try_merge_passage(
                        query_index,
                        passage_index,
                        passage,
                        reserve_limit=None,
                    )
                    if len(merged_passages) > before_count:
                        returned_by_pmid[passage.pmid] += 1

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

    text_chars, estimated_tokens = pack_totals(merged_passages)
    budget_text_chars = text_chars
    if request.response_mode == "full":
        budget_text_chars += sum(
            result.context_pack.total_chars
            or sum(len(passage.text) for passage in result.context_pack.passages)
            for result in query_results
        )
    return MergedBatchContext(
        passages=merged_passages,
        dropped=dropped,
        query_summaries=query_summaries,
        source_budget_summaries=[
            source_budget_stats[source_key] for source_key in source_budget_order
        ],
        pmid_status_summary=[pmid_stats[pmid] for pmid in pmid_order],
        text_chars=text_chars,
        estimated_tokens=estimated_tokens,
        budget_text_chars=budget_text_chars,
    )
