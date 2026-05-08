"""Shared compact serialization and ranking helpers for literature graph tools."""

from __future__ import annotations

import json
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from pubtator_link.models.literature_graph import (
    LiteratureAuthor,
    LiteratureCandidateAccess,
    LiteratureCandidateSummary,
    LiteratureGraphResponseMeta,
    LiteratureGraphResponseMode,
    LiteraturePaper,
    LiteratureQueryRelevance,
    LiteratureResponseSizeClass,
    LiteratureSourceTool,
    ProviderWarning,
)
from pubtator_link.services.literature_paper_resolution import deduped_signals
from pubtator_link.services.provenance import corpus_snapshot_date, stable_cache_key

COMPACT_BUDGET_BYTES = 12 * 1024
NODES_EDGES_BUDGET_BYTES = 40 * 1024
GRAPH_PAYLOAD_CONTRACT_VERSION = "literature_graph_payload_controls_v1"
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


def graph_payload_json_bytes(payload: Any) -> int:
    if hasattr(payload, "model_dump_json"):
        return len(payload.model_dump_json(by_alias=True).encode("utf-8"))
    return len(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def graph_request_metadata(
    *,
    tool_name: str,
    request: Any,
    source_versions: Mapping[str, str] | None = None,
) -> LiteratureGraphResponseMeta:
    versions = {
        "payload_contract": GRAPH_PAYLOAD_CONTRACT_VERSION,
        **dict(source_versions or {}),
    }
    request_signature = stable_cache_key(
        "literature_graph",
        {
            "tool": tool_name,
            "request": request.model_dump(mode="json"),
        },
    )
    return LiteratureGraphResponseMeta(
        response_mode=request.response_mode,
        request_signature=request_signature,
        cache_key=request_signature,
        snapshot_date=corpus_snapshot_date(),
        source_versions=versions,
    )


def graph_detail_next_commands(
    *,
    tool_name: str,
    request: Any,
    modes: tuple[LiteratureGraphResponseMode, ...],
) -> list[dict[str, Any]]:
    request_args = request.model_dump(mode="json", exclude_none=True)
    return [
        {
            "tool": tool_name,
            "arguments": {**request_args, "response_mode": mode},
        }
        for mode in modes
        if mode != request.response_mode
    ]


def graph_budget_bytes(response_mode: LiteratureGraphResponseMode) -> int | None:
    if response_mode == "compact":
        return COMPACT_BUDGET_BYTES
    if response_mode == "nodes_edges":
        return NODES_EDGES_BUDGET_BYTES
    return None


def mark_graph_payload_truncated(
    meta: LiteratureGraphResponseMeta,
    *,
    omitted_counts: Mapping[str, int],
    budget_bytes: int,
) -> LiteratureGraphResponseMeta:
    merged = dict(meta.omitted_counts)
    for key, count in omitted_counts.items():
        if count > 0:
            merged[key] = merged.get(key, 0) + count
    return meta.model_copy(
        update={
            "truncated": True,
            "omitted_counts": merged,
            "budget_advice": (
                f"Response was compacted to stay within the {budget_bytes} byte "
                f"({budget_bytes // 1024} KiB) graph payload budget; request "
                "response_mode='full' or narrower inputs for detail."
            ),
        }
    )


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
    signals = deduped_signals(
        relevance_to_query.reasons if relevance_to_query is not None else [],
        rank_reasons or [],
        demotion_reasons or [],
    )
    author_label, author_count = compact_author_summary(paper.authors)
    return LiteratureCandidateSummary(
        pmid=paper.pmid,
        doi=paper.doi,
        title=paper.title,
        journal=paper.journal,
        year=paper.year,
        publication_types=paper.publication_types,
        author_summary=author_label,
        author_count=author_count,
        access=access_summary(paper),
        access_flags=access_flags(paper),
        score=score,
        relevance_to_query=relevance_to_query,
        rank_reasons=rank_reasons or [],
        demotion_reasons=demotion_reasons or [],
        signals=signals,
        source_tools=source_tools or [],
        next_actions=(
            [{"tool": "pubtator.get_publication_passages", "arguments": {"pmids": [paper.pmid]}}]
            if paper.pmid
            else []
        ),
    )


def compact_author_summary(authors: Iterable[LiteratureAuthor]) -> tuple[str | None, int]:
    names = [author.name for author in authors if author.name]
    count = len(names)
    if count == 0:
        return None, 0
    if count <= 3:
        return ", ".join(names), count
    return f"{', '.join(names[:3])} et al. ({count} authors)", count
