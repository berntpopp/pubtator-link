from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import cast

from pubtator_link.models.review_rerag import (
    ContextDropReason,
    ContextPassage,
    PmidStatusSummary,
    QueryDiagnosticsSummary,
    RecoveryBudgetAdvice,
    RecoverySuggestedFilters,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextResponse,
    SourceBudgetSummary,
    SourceCoverage,
    SourceDroppedSummary,
    estimate_tokens_from_chars,
)
from pubtator_link.services.review_context.diagnostics import query_summary
from pubtator_link.services.review_context.packing import context_budget, pack_totals
from pubtator_link.services.review_context.ranking import SOURCE_COVERAGE_SCARCITY_PRIORITY

MAX_DROPPED_ITEMS = 10
QUOTE_MAX_CHARS = 350
QUOTE_PAYLOAD_OVERHEAD_CHARS = 180
_CLAIM_SIGNAL_RE = re.compile(
    r"\b("
    r"recommend(?:ation|ed|s)?|guideline|should|must|therapy|treatment|dose|"
    r"efficacy|response|remission|attack|risk|compared|versus|higher|lower|"
    r"significant|children|pediatric|patient|cohort"
    r")\b",
    re.IGNORECASE,
)
_BACKGROUND_STUB_RE = re.compile(
    r"\b("
    r"located on chromosome|caused by mutations|most common monogenic|"
    r"is the most frequent|is the oldest|gene located"
    r")\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]*")


@dataclass
class MergedBatchContext:
    passages: list[ContextPassage]
    dropped: list[ContextDropReason]
    dropped_summary: SourceDroppedSummary
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
    passage_by_id: dict[str, ContextPassage] = {}
    handled_passages: set[tuple[int, int]] = set()
    returned_counts: list[int] = []
    dropped_counts: list[int] = []
    query_chars: list[int] = []
    source_budget_stats: dict[str | None, SourceBudgetSummary] = {}
    source_budget_order: list[str | None] = []
    pmid_stats: dict[str, PmidStatusSummary] = {}
    pmid_order: list[str] = []
    total_chars = 0
    total_quote_payload_chars = 0
    max_response_chars = cast(int, request.max_response_chars)
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
        nonlocal total_chars, total_quote_payload_chars
        seen_passage_ids.add(passage.passage_id)
        merged_passages.append(
            passage.model_copy(
                update={
                    "citation_key": f"S{len(merged_passages) + 1}",
                    "stable_citation_key": passage.stable_citation_key,
                    "char_count": len(passage.text),
                    "matched_queries": [request.queries[query_index]],
                    "matched_query_indices": [query_index],
                }
            )
        )
        passage_by_id[passage.passage_id] = merged_passages[-1]
        passage_len = len(passage.text)
        total_chars += passage_len
        if request.response_mode == "quotes":
            total_quote_payload_chars += quote_payload_chars(merged_passages[-1])
        query_chars[query_index] += passage_len
        returned_counts[query_index] += 1
        if source_key in source_budget_stats:
            source_budget_stats[source_key].returned_count += 1
        pmid_summary = ensure_pmid_summary(passage.pmid)
        if pmid_summary is not None:
            pmid_summary.passages_returned += 1

    def add_duplicate_match(query_index: int, passage: ContextPassage) -> None:
        merged_passage = passage_by_id.get(passage.passage_id)
        if merged_passage is None:
            return
        if query_index not in merged_passage.matched_query_indices:
            merged_passage.matched_query_indices.append(query_index)
            merged_passage.matched_queries.append(request.queries[query_index])
            returned_counts[query_index] += 1

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
            add_duplicate_match(query_index, passage)
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
        if request.response_mode == "quotes":
            next_quote_payload_chars = total_quote_payload_chars + quote_payload_chars(
                passage,
                matched_queries=[request.queries[query_index]],
            )
            if next_quote_payload_chars > max_response_chars:
                drop_passage(
                    query_index,
                    passage,
                    "response_char_budget_exceeded",
                    source_key=source_key,
                )
                return True
        elif request.response_mode != "full":
            next_budget = context_budget(
                max_chars=request.max_chars,
                text_chars=total_chars + passage_len,
                dropped_count=len(dropped),
            )
            if next_budget.estimated_total_chars > max_response_chars:
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

            def pmid_floor_sort_key(
                candidate: tuple[int, int, ContextPassage],
            ) -> tuple[int, int, int]:
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
                passages = _ordered_passages_for_mode(
                    request=request,
                    query_index=query_index,
                    passages=result.context_pack.passages,
                )
                for passage_index, passage in passages:
                    try_merge_passage(
                        query_index,
                        passage_index,
                        passage,
                        reserve_limit=reserve_limit,
                    )
            for query_index, result in enumerate(query_results):
                passages = _ordered_passages_for_mode(
                    request=request,
                    query_index=query_index,
                    passages=result.context_pack.passages,
                )
                for passage_index, passage in passages:
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
    visible_dropped = dropped[:MAX_DROPPED_ITEMS]
    dropped_summary = build_dropped_summary(
        dropped=dropped,
        visible_dropped=visible_dropped,
        request=request,
    )
    return MergedBatchContext(
        passages=merged_passages,
        dropped=visible_dropped,
        dropped_summary=dropped_summary,
        query_summaries=query_summaries,
        source_budget_summaries=[
            source_budget_stats[source_key] for source_key in source_budget_order
        ],
        pmid_status_summary=[pmid_stats[pmid] for pmid in pmid_order],
        text_chars=text_chars,
        estimated_tokens=estimated_tokens,
        budget_text_chars=budget_text_chars,
    )


def quote_payload_chars(
    passage: ContextPassage,
    *,
    matched_queries: list[str] | None = None,
) -> int:
    quote = passage.quote.text.strip() if passage.quote is not None else ""
    if not quote:
        quote = " ".join(passage.text.split())
    quote_chars = min(len(quote), QUOTE_MAX_CHARS)
    queries = passage.matched_queries if matched_queries is None else matched_queries
    return (
        QUOTE_PAYLOAD_OVERHEAD_CHARS
        + len(passage.stable_citation_key or "")
        + len(passage.pmid or "")
        + len(passage.passage_id)
        + len(passage.section)
        + quote_chars
        + sum(len(query) for query in queries)
    )


def _ordered_passages_for_mode(
    *,
    request: RetrieveReviewContextBatchRequest,
    query_index: int,
    passages: list[ContextPassage],
) -> list[tuple[int, ContextPassage]]:
    indexed = list(enumerate(passages))
    if request.response_mode != "quotes":
        return indexed
    query = request.queries[query_index] if query_index < len(request.queries) else ""
    return sorted(
        indexed,
        key=lambda item: (
            -_claim_density_score(item[1], query=query),
            item[0],
        ),
    )


def _claim_density_score(passage: ContextPassage, *, query: str) -> float:
    quote = passage.quote.text if passage.quote is not None else passage.text
    text = " ".join(quote.split())
    lowered = text.lower()
    score = 0.0
    if _CLAIM_SIGNAL_RE.search(text):
        score += 2.0
    if any(char.isdigit() for char in text):
        score += 1.5
    if _BACKGROUND_STUB_RE.search(text):
        score -= 3.0
    content_terms = {token.lower() for token in _WORD_RE.findall(lowered) if len(token) > 2}
    query_terms = {token.lower() for token in _WORD_RE.findall(query.lower()) if len(token) > 2}
    if content_terms:
        query_dominance = len(content_terms.intersection(query_terms)) / len(content_terms)
        if query_dominance > 0.5:
            score -= 2.0
    return score


def build_dropped_summary(
    *,
    dropped: list[ContextDropReason],
    visible_dropped: list[ContextDropReason],
    request: RetrieveReviewContextBatchRequest,
) -> SourceDroppedSummary:
    by_reason = dict(Counter(item.reason for item in dropped))
    section_counts = Counter(item.section for item in dropped if item.section)
    pmid_counts = Counter(item.pmid for item in dropped if item.pmid)
    max_response_chars = cast(int, request.max_response_chars)
    budget_reasons = {
        "char_budget_exceeded",
        "response_char_budget_exceeded",
        "passage_over_max_chars_per_passage",
    }
    budget_advice = None
    budget_drops = [item for item in dropped if item.reason in budget_reasons]
    if budget_drops:
        increase_max_chars_to = min(
            50000,
            max(request.max_chars + 2000, int(request.max_chars * 1.5)),
        )
        increase_max_response_chars_to = min(
            100000,
            max(
                max_response_chars + 4000,
                int(max_response_chars * 1.5),
            ),
        )
        lower_max_passages_per_query_to = max(1, request.max_passages_per_query // 2)
        dropped_pmids = list(dict.fromkeys(item.pmid for item in budget_drops if item.pmid))
        dropped_priority_pmids = [
            pmid for pmid in request.prioritize_pmids if pmid in set(dropped_pmids)
        ][:5]
        estimated_tokens_to_unlock = estimate_tokens_from_chars(
            sum(item.char_count or 0 for item in budget_drops)
        )
        retry_arguments: dict[str, object] = {
            "max_chars": increase_max_chars_to,
            "max_response_chars": increase_max_response_chars_to,
            "max_passages_per_query": lower_max_passages_per_query_to,
        }
        if dropped_priority_pmids:
            retry_arguments["prioritize_pmids"] = dropped_priority_pmids
        budget_advice = RecoveryBudgetAdvice(
            increase_max_chars_to=increase_max_chars_to,
            increase_max_response_chars_to=increase_max_response_chars_to,
            lower_max_passages_per_query_to=lower_max_passages_per_query_to,
            estimated_tokens_to_unlock=estimated_tokens_to_unlock,
            dropped_pmid_count=len(dropped_pmids),
            dropped_priority_pmids=dropped_priority_pmids,
            retry_arguments=retry_arguments,
        )
    return SourceDroppedSummary(
        total_dropped=len(dropped),
        visible_dropped=len(visible_dropped),
        truncated_count=max(0, len(dropped) - len(visible_dropped)),
        by_reason=by_reason,
        suggested_filters=RecoverySuggestedFilters(
            sections=[section for section, _count in section_counts.most_common(3)],
            pmids=[pmid for pmid, _count in pmid_counts.most_common(5)],
        ),
        budget_advice=budget_advice,
    )
