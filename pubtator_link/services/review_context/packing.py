from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from pubtator_link.models.review_rerag import (
    ContextBudget,
    ContextDropReason,
    ContextPassage,
    RetrieveReviewContextRequest,
    ReviewPassageRow,
    estimate_tokens_from_chars,
)


@dataclass(frozen=True)
class PackedPassages:
    selected: list[ReviewPassageRow]
    dropped: list[ContextDropReason]


def pack_passages(
    candidates: list[ReviewPassageRow],
    request: RetrieveReviewContextRequest,
) -> PackedPassages:
    selected: list[ReviewPassageRow] = []
    dropped: list[ContextDropReason] = []
    pmid_counts: dict[str, int] = defaultdict(int)
    total_chars = 0
    enforce_pmid_diversity = len(request.pmids) != 1

    for row in candidates:
        if len(selected) >= request.max_passages:
            break
        if not section_allowed(row, request):
            continue
        if (
            enforce_pmid_diversity
            and row.pmid is not None
            and pmid_counts[row.pmid] >= request.max_passages_per_pmid
        ):
            continue
        effective_len = effective_passage_len(row, request)
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

    return PackedPassages(selected=selected, dropped=dropped)


def context_passage_from_row(
    *,
    index: int,
    row: ReviewPassageRow,
    request: RetrieveReviewContextRequest,
) -> ContextPassage:
    text, start_char, end_char, truncated = excerpt_text(
        row.text,
        query_tokens=_query_tokens(request.question),
        max_chars=request.max_chars_per_passage,
        allow_truncated=request.allow_truncated_passages,
    )
    return ContextPassage(
        citation_key=f"S{index}",
        passage_id=row.passage_id,
        source_id=row.source_id,
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


def effective_passage_len(
    row: ReviewPassageRow, request: RetrieveReviewContextRequest
) -> int | None:
    if len(row.text) <= request.max_chars_per_passage:
        return len(row.text)
    if not request.allow_truncated_passages:
        return None
    return request.max_chars_per_passage


def is_table_section(section: str) -> bool:
    return "table" in section.strip().lower()


def is_reference_section(section: str) -> bool:
    lowered = section.strip().lower()
    return lowered in {"ref", "refs", "reference", "references", "bibliography"} or (
        "reference" in lowered
    )


def section_allowed(row: ReviewPassageRow, request: RetrieveReviewContextRequest) -> bool:
    if is_reference_section(row.section) and not request.include_references:
        return False
    if is_table_section(row.section):
        return request.include_tables or request.table_mode == "full"
    return True


def excerpt_text(
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


def context_budget(max_chars: int, text_chars: int, dropped_count: int = 0) -> ContextBudget:
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


def pack_totals(passages: Sequence[ContextPassage]) -> tuple[int, int]:
    text_chars = sum(len(passage.text) for passage in passages)
    return text_chars, estimate_tokens_from_chars(text_chars)


def _query_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[a-zA-Z0-9]+", query.lower()):
        if len(token) < 3 or token in {"and", "the", "for", "with", "from"}:
            continue
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= 8:
            break
    return tokens
