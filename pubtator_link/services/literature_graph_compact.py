"""Shared compact serialization and ranking helpers for literature graph tools."""

from __future__ import annotations

import json
import unicodedata
from collections import Counter
from collections.abc import Iterable
from typing import Any

from pubtator_link.models.literature_graph import (
    LiteratureCandidateAccess,
    LiteratureCandidateSummary,
    LiteraturePaper,
    LiteratureQueryRelevance,
    LiteratureResponseSizeClass,
    LiteratureSourceTool,
    ProviderWarning,
)

COMPACT_BUDGET_BYTES = 12 * 1024
NODES_EDGES_BUDGET_BYTES = 40 * 1024
TOPIC_RANKING_VERSION = "topic_map_ranker_v1"

_INTENT_TERMS: dict[str, tuple[str, ...]] = {
    "guideline_intent": ("guideline", "recommendation", "consensus", "delphi"),
    "pediatric_intent": ("child", "children", "pediatric", "paediatric"),
    "population_intent": ("turkey", "turkish", "mediterranean", "ancestry"),
    "variant_intent": ("variant", "vus", "genotype", "phenotype", "penetrance"),
    "treatment_intent": ("colchicine", "treatment", "resistance", "management"),
}


def access_flags(paper: LiteraturePaper) -> dict[str, bool]:
    return {
        "has_pmc_full_text": bool(paper.availability.has_pmc_full_text or paper.pmcid),
        "is_open_access": bool(paper.availability.is_open_access),
        "has_pdf": bool(paper.availability.has_pdf),
    }


def access_summary(paper: LiteraturePaper) -> LiteratureCandidateAccess:
    flags = access_flags(paper)
    if flags["has_pmc_full_text"]:
        return "full_text"
    if flags["is_open_access"] or paper.availability.full_text_url:
        return "open_access"
    if paper.pmid or paper.doi or paper.title:
        return "metadata_only"
    return "unresolved"


def response_size_class(num_bytes: int) -> LiteratureResponseSizeClass:
    if num_bytes <= 4 * 1024:
        return "small"
    if num_bytes <= COMPACT_BUDGET_BYTES:
        return "medium"
    return "large"


def json_size_class(payload: dict[str, Any]) -> LiteratureResponseSizeClass:
    return response_size_class(len(json.dumps(payload, separators=(",", ":"), default=str)))


def coalesced_provider_warnings(warnings: Iterable[ProviderWarning]) -> list[ProviderWarning]:
    grouped: dict[tuple[str, str, str, bool], int] = Counter(
        (warning.provider, warning.status, warning.message, warning.retryable)
        for warning in warnings
    )
    return [
        ProviderWarning(
            provider=provider,
            status=status,
            retryable=retryable,
            message=message if count == 1 else f"{message} (repeated {count} times)",
        )
        for (provider, status, message, retryable), count in grouped.items()
    ]


def normalize_query_text(query: str | None) -> str:
    if not query:
        return ""
    return unicodedata.normalize("NFKC", query).casefold()


def intent_flags_for_query(query: str | None) -> set[str]:
    normalized = normalize_query_text(query)
    flags: set[str] = set()
    for flag, terms in _INTENT_TERMS.items():
        if any(term in normalized for term in terms):
            flags.add(flag)
    return flags


def candidate_summary(
    paper: LiteraturePaper,
    *,
    score: float | None = None,
    relevance_to_query: LiteratureQueryRelevance | None = None,
    rank_reasons: list[str] | None = None,
    demotion_reasons: list[str] | None = None,
    source_tools: list[LiteratureSourceTool] | None = None,
) -> LiteratureCandidateSummary:
    return LiteratureCandidateSummary(
        pmid=paper.pmid,
        doi=paper.doi,
        title=paper.title,
        journal=paper.journal,
        year=paper.year,
        publication_types=paper.publication_types,
        access=access_summary(paper),
        access_flags=access_flags(paper),
        score=score,
        relevance_to_query=relevance_to_query,
        rank_reasons=rank_reasons or [],
        demotion_reasons=demotion_reasons or [],
        source_tools=source_tools or [],
        next_actions=(
            [{"tool": "pubtator.get_publication_passages", "arguments": {"pmids": [paper.pmid]}}]
            if paper.pmid
            else []
        ),
    )
