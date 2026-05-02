from __future__ import annotations

import re
from typing import Any, Literal

from pubtator_link.models.publication_metadata import PublicationAuthor
from pubtator_link.models.responses import SearchResponse, SearchResult
from pubtator_link.services.provenance import corpus_snapshot_date, stable_cache_key

SearchResponseMode = Literal["compact", "standard", "full"]
IncludeCitations = Literal["none", "nlm", "bibtex", "both"]
TextHighlightFormat = Literal["none", "plain", "annotated"]
SearchMetadataMode = Literal["none", "basic", "full"]

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
    metadata: SearchMetadataMode = "none",
    metadata_by_pmid: dict[str, dict[str, Any]] | None = None,
) -> SearchResponse:
    raw_items = list(raw.get("results", []))
    raw_items = selected_search_items(raw_items, guideline_boost=guideline_boost, limit=limit)

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
                metadata=metadata,
                metadata_item=(metadata_by_pmid or {}).get(str(item.get("pmid", ""))),
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
        corpus_snapshot_date=corpus_snapshot_date(),
        source_versions={"pubtator3": "live"},
    )


def shaped_search_result(
    *,
    item: dict[str, Any],
    response_mode: SearchResponseMode,
    include_citations: IncludeCitations,
    text_hl_format: TextHighlightFormat,
    guideline_boost: bool,
    metadata: SearchMetadataMode = "none",
    metadata_item: dict[str, Any] | None = None,
) -> SearchResult:
    rank_features = _guideline_rank_features(item) if guideline_boost else None
    include_text_hl = text_hl_format != "none"
    shaped = SearchResult(
        pmid=item.get("pmid", ""),
        title=item.get("title", ""),
        abstract=item.get("abstract") if response_mode in {"standard", "full"} else None,
        authors=(
            _shape_authors(item.get("authors", [])) if response_mode in {"standard", "full"} else []
        ),
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
    _merge_metadata_fields(shaped, metadata, metadata_item)
    return shaped


def _merge_metadata_fields(
    shaped: SearchResult,
    metadata: SearchMetadataMode,
    metadata_item: dict[str, Any] | None,
) -> None:
    if metadata == "none" or metadata_item is None:
        return

    basic_fields = (
        "authors",
        "journal",
        "pub_year",
        "pub_date",
        "volume",
        "issue",
        "pages",
        "doi",
        "pmcid",
        "publication_types",
    )
    full_fields = (*basic_fields, "mesh_headings", "nlm_citation", "bibtex")
    for field_name in full_fields if metadata == "full" else basic_fields:
        if _has_metadata_value(getattr(shaped, field_name)):
            continue
        if field_name in metadata_item and _has_metadata_value(metadata_item[field_name]):
            value = metadata_item[field_name]
            if field_name == "authors":
                value = _shape_authors(value)
            setattr(shaped, field_name, value)


def _has_metadata_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def _shape_authors(authors: Any) -> list[PublicationAuthor]:
    if not isinstance(authors, list):
        return []
    shaped: list[PublicationAuthor] = []
    for author in authors:
        if isinstance(author, PublicationAuthor):
            shaped.append(author)
        elif isinstance(author, str):
            stripped = author.strip()
            if stripped:
                shaped.append(PublicationAuthor(collective_name=stripped))
        elif isinstance(author, dict):
            shaped.append(PublicationAuthor.model_validate(author))
    return shaped


def search_cache_key(
    *,
    text: str,
    page: int,
    sort: str | None,
    filters: str | None,
    sections: list[str] | None,
) -> str:
    return stable_cache_key(
        "search",
        {
            "text": text,
            "page": page,
            "sort": sort,
            "filters": filters,
            "sections": sections or [],
        },
    )


def _rerank_guidelines(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        enumerate(items),
        key=lambda pair: (-_guideline_rank_features(pair[1])["guideline_boost"], pair[0]),
    )
    return [item for _, item in ranked]


def selected_search_items(
    items: list[dict[str, Any]],
    *,
    guideline_boost: bool,
    limit: int | None,
) -> list[dict[str, Any]]:
    selected = _rerank_guidelines(items) if guideline_boost else items
    return selected[:limit] if limit is not None else selected


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
        3 for value in publication_types if any(term in value for term in GUIDELINE_TYPES)
    )
    term_boost = sum(1 for term in GUIDELINE_TERMS if term in title or term in abstract)
    return {"guideline_boost": type_boost + term_boost}
