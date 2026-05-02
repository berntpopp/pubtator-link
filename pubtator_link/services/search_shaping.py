from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any, Literal

from pubtator_link.models.responses import SearchResponse, SearchResult

SearchResponseMode = Literal["compact", "standard", "full"]
IncludeCitations = Literal["none", "nlm", "bibtex", "both"]
TextHighlightFormat = Literal["none", "plain", "annotated"]

GUIDELINE_TERMS = ("recommendation", "guideline", "consensus", "eular", "pres", "share")
GUIDELINE_TYPES = (
    "guideline",
    "practice guideline",
    "consensus",
    "consensus development conference",
    "systematic review",
)


def combined_search_text(text: str, entity_ids: list[str] | None) -> str:
    ids = [item.strip() for item in entity_ids or [] if item.strip()]
    if not ids:
        return text.strip()
    entity_query = " AND ".join(ids)
    stripped = text.strip()
    return f"({stripped}) AND {entity_query}" if stripped else entity_query


def shaped_search_response(
    *,
    raw: dict[str, Any],
    query: str,
    page: int,
    sort: str | None,
    filters: str | None,
    sections: list[str] | None,
    response_mode: SearchResponseMode,
    include_citations: IncludeCitations,
    text_hl_format: TextHighlightFormat,
    limit: int | None,
    guideline_boost: bool,
) -> SearchResponse:
    raw_items = list(raw.get("results", []))
    if guideline_boost:
        raw_items = _rerank_guidelines(raw_items)
    if limit is not None:
        raw_items = raw_items[:limit]

    total_results = int(raw.get("count", raw.get("total", 0)))
    per_page = int(raw.get("page_size", raw.get("per_page", 20)))
    return SearchResponse(
        success=True,
        query=query,
        results=[
            shaped_search_result(
                item=item,
                response_mode=response_mode,
                include_citations=include_citations,
                text_hl_format=text_hl_format,
                guideline_boost=guideline_boost,
            )
            for item in raw_items
        ],
        total_results=total_results,
        page=page,
        per_page=per_page,
        total_pages=int(
            raw.get(
                "total_pages",
                (total_results + per_page - 1) // per_page if per_page else 0,
            )
        ),
        sort_order=sort,
        cache_key=search_cache_key(
            text=query,
            page=page,
            sort=sort,
            filters=filters,
            sections=sections,
        ),
        corpus_snapshot_date=date.today().isoformat(),
        source_versions={"pubtator3": "live"},
    )


def shaped_search_result(
    *,
    item: dict[str, Any],
    response_mode: SearchResponseMode,
    include_citations: IncludeCitations,
    text_hl_format: TextHighlightFormat,
    guideline_boost: bool,
) -> SearchResult:
    rank_features = _guideline_rank_features(item) if guideline_boost else None
    include_text_hl = text_hl_format != "none"
    return SearchResult(
        pmid=item.get("pmid", ""),
        title=item.get("title", ""),
        abstract=item.get("abstract") if response_mode in {"standard", "full"} else None,
        authors=item.get("authors", []) if response_mode in {"standard", "full"} else [],
        journal=item.get("journal"),
        pub_date=item.get("pub_date") or item.get("meta_date_publication") or item.get("date"),
        annotations=item.get("annotations", []) if response_mode == "full" else [],
        score=item.get("score"),
        pmcid=item.get("pmcid"),
        doi=item.get("doi"),
        date=item.get("date"),
        text_hl=_shape_text_hl(item.get("text_hl"), text_hl_format) if include_text_hl else None,
        citations=_shape_citations(item.get("citations"), include_citations),
        volume=item.get("volume") or item.get("meta_volume"),
        issue=item.get("issue") or item.get("meta_issue"),
        pages=item.get("pages") or item.get("meta_pages"),
        publication_types=item.get("publication_types", []),
        coverage_hint=item.get("coverage_hint"),
        rank_features=rank_features,
        matched_terms=item.get("matched_terms", []),
    )


def search_cache_key(
    *,
    text: str,
    page: int,
    sort: str | None,
    filters: str | None,
    sections: list[str] | None,
) -> str:
    raw = "|".join([text, str(page), sort or "", filters or "", ",".join(sections or [])])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _rerank_guidelines(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        enumerate(items),
        key=lambda pair: (-_guideline_rank_features(pair[1])["guideline_boost"], pair[0]),
    )
    return [item for _, item in ranked]


def _shape_text_hl(value: str | None, mode: TextHighlightFormat) -> str | None:
    if value is None or mode == "annotated":
        return value
    text = re.sub(r"@@@([^@]+)@@@", r"\1", value)
    text = re.sub(r"@\w+(?::[\w.-]+)?", "", text)
    text = re.sub(r"</?m>", "", text)
    return " ".join(text.split())


def _shape_citations(
    citations: dict[str, str] | None,
    mode: IncludeCitations,
) -> dict[str, str] | None:
    if not citations or mode == "none":
        return None
    shaped: dict[str, str] = {}
    if mode in {"nlm", "both"}:
        key = "NLM" if "NLM" in citations else "nlm" if "nlm" in citations else None
        if key is not None:
            shaped[key] = citations[key]
    if mode in {"bibtex", "both"}:
        key = "BibTeX" if "BibTeX" in citations else "bibtex" if "bibtex" in citations else None
        if key is not None:
            shaped[key] = citations[key]
    return shaped or None


def _guideline_rank_features(item: dict[str, Any]) -> dict[str, Any]:
    publication_types = [str(value).lower() for value in item.get("publication_types", [])]
    title = str(item.get("title") or "").lower()
    abstract = str(item.get("abstract") or "").lower()
    type_boost = sum(
        3
        for value in publication_types
        if any(term in value for term in GUIDELINE_TYPES)
    )
    term_boost = sum(1 for term in GUIDELINE_TERMS if term in title or term in abstract)
    return {"guideline_boost": type_boost + term_boost}
