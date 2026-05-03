from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from pubtator_link.models.review_rerag import (
    FailedSourceSummary,
    QueryDiagnosticsSummary,
    RecoveryBudgetAdvice,
    RecoveryHint,
    RecoverySuggestedFilters,
    RetrieveReviewContextRequest,
    RetrieveReviewContextResponse,
    RetrieveReviewDiagnostics,
    ZeroResultReason,
)


class DiagnosticsRepository(Protocol):
    async def available_sections(
        self, review_id: str, *, session_id: str | None = None
    ) -> list[str]:
        """Return indexed section names for diagnostics."""

    async def indexed_pmids(self, review_id: str, *, session_id: str | None = None) -> list[str]:
        """Return indexed PMIDs for diagnostics."""

    async def list_review_failed_sources(
        self, review_id: str, *, session_id: str | None = None
    ) -> list[FailedSourceSummary]:
        """Return failed source summaries for diagnostics."""


def query_summary(
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
    suggested_queries_value = diagnostics.suggested_queries if diagnostics else []
    query_tokens_value = diagnostics.query_tokens if diagnostics else query_tokens(query)
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
    elif dropped_count >= returned_count * 3 and dropped_count >= 3:
        next_steps = ["increase_budget", "narrow_query", "inspect_review_index"]
    return QueryDiagnosticsSummary(
        query=query,
        query_tokens=query_tokens_value,
        candidate_count=candidate_count,
        selected_count=selected_count,
        returned_count=returned_count,
        dropped_count=dropped_count,
        top_sections=top_sections,
        top_pmids=top_pmids,
        zero_result_reason=zero_result_reason,
        suggested_queries=suggested_queries_value,
        next_steps=next_steps,
    )


def recovery_from_query_summary(summary: QueryDiagnosticsSummary) -> RecoveryHint | None:
    if summary.returned_count == 0 and summary.zero_result_reason is not None:
        return RecoveryHint(
            reason=summary.zero_result_reason,
            message=f"No passages returned for query: {summary.query}",
            next_steps=summary.next_steps,
            suggested_queries=summary.suggested_queries,
            suggested_filters=RecoverySuggestedFilters(
                sections=summary.top_sections[:3],
                pmids=summary.top_pmids[:5],
            ),
        )
    if summary.dropped_count >= max(3, summary.returned_count * 3):
        return RecoveryHint(
            reason="high_drop_pressure",
            message=f"Many candidate passages were dropped for query: {summary.query}",
            next_steps=summary.next_steps or ["increase_budget", "filter_sections"],
            suggested_queries=summary.suggested_queries,
            suggested_filters=RecoverySuggestedFilters(
                sections=summary.top_sections[:3],
                pmids=summary.top_pmids[:5],
            ),
            budget_advice=RecoveryBudgetAdvice(
                increase_max_chars_to=18000,
                increase_max_response_chars_to=36000,
                lower_max_passages_per_query_to=4,
            ),
        )
    return None


async def build_diagnostics(
    *,
    repository: DiagnosticsRepository,
    review_id: str,
    request: RetrieveReviewContextRequest,
    candidate_count: int,
    selected_count: int,
    available_sections: Sequence[str] | None = None,
    indexed_pmids: Sequence[str] | None = None,
    failed_sources: Sequence[FailedSourceSummary] | None = None,
) -> RetrieveReviewDiagnostics:
    query_tokens_value = query_tokens(request.question)
    available_sections_value = (
        list(available_sections)
        if available_sections is not None
        else await repository.available_sections(review_id, session_id=request.session_id)
    )
    indexed_pmids_value = (
        list(indexed_pmids)
        if indexed_pmids is not None
        else await repository.indexed_pmids(review_id, session_id=request.session_id)
    )
    failed_sources_value = (
        list(failed_sources)
        if failed_sources is not None
        else await repository.list_review_failed_sources(review_id, session_id=request.session_id)
    )
    section_label = ", ".join(available_sections_value) if available_sections_value else "none"
    message = (
        f"No passages selected. Review {review_id} has {len(indexed_pmids_value)} indexed PMIDs "
        f"and sections {section_label}. Try shorter keyword queries or remove section filters."
        if selected_count == 0
        else f"Selected {selected_count} passages from {candidate_count} candidates."
    )
    return RetrieveReviewDiagnostics(
        query=request.question,
        query_tokens=query_tokens_value,
        candidate_count=candidate_count,
        selected_count=selected_count,
        available_sections=available_sections_value,
        indexed_pmids=indexed_pmids_value,
        failed_sources=failed_sources_value,
        filter_summary={
            "pmids": list(request.pmids),
            "entity_ids": list(request.entity_ids),
            "sections": list(request.sections),
        },
        suggested_queries=suggested_queries(query_tokens_value, available_sections_value),
        message=message,
    )


def query_tokens(query: str) -> list[str]:
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


def suggested_queries(tokens: list[str], available_sections: Sequence[str]) -> list[str]:
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
