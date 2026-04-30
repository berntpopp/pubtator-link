from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from pubtator_link.models.review_rerag import (
    FailedSourceSummary,
    QueryDiagnosticsSummary,
    RetrieveReviewContextRequest,
    RetrieveReviewContextResponse,
    RetrieveReviewDiagnostics,
    ZeroResultReason,
)


class DiagnosticsRepository(Protocol):
    async def available_sections(self, review_id: str) -> list[str]:
        """Return indexed section names for diagnostics."""

    async def indexed_pmids(self, review_id: str) -> list[str]:
        """Return indexed PMIDs for diagnostics."""

    async def list_review_failed_sources(self, review_id: str) -> list[FailedSourceSummary]:
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


async def build_diagnostics(
    *,
    repository: DiagnosticsRepository,
    review_id: str,
    request: RetrieveReviewContextRequest,
    candidate_count: int,
    selected_count: int,
) -> RetrieveReviewDiagnostics:
    query_tokens_value = query_tokens(request.question)
    available_sections = await repository.available_sections(review_id)
    indexed_pmids = await repository.indexed_pmids(review_id)
    failed_sources = await repository.list_review_failed_sources(review_id)
    section_label = ", ".join(available_sections) if available_sections else "none"
    message = (
        f"No passages selected. Review {review_id} has {len(indexed_pmids)} indexed PMIDs "
        f"and sections {section_label}. Try shorter keyword queries or remove section filters."
        if selected_count == 0
        else f"Selected {selected_count} passages from {candidate_count} candidates."
    )
    return RetrieveReviewDiagnostics(
        query=request.question,
        query_tokens=query_tokens_value,
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
        suggested_queries=suggested_queries(query_tokens_value, available_sections),
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
