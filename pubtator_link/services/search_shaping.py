from __future__ import annotations

import re
from typing import Any, Literal

from pubtator_link.models.publication_metadata import PublicationAuthor
from pubtator_link.models.responses import SearchResponse, SearchResult
from pubtator_link.services.provenance import corpus_snapshot_date, stable_cache_key

SearchResponseMode = Literal["compact", "standard", "full"]
IncludeCitations = Literal["none", "nlm", "bibtex", "both"]
TextHighlightFormat = Literal["none", "plain", "annotated"]
SearchMetadataMode = Literal["none", "basic", "with_abstract", "full"]
INLINE_ABSTRACT_MAX_CHARS = 640

GUIDELINE_TERMS = (
    "recommendation",
    "guideline",
    "consensus",
    "eular",
    "pres",
    "share",
    "systematic review",
    "systematic-review",
)
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


def dump_search_response(
    response: SearchResponse, *, response_mode: SearchResponseMode
) -> dict[str, Any]:
    dumped = response.model_dump(exclude_none=response_mode == "compact")
    if response_mode != "compact":
        return dumped
    for result in dumped.get("results", []):
        if not isinstance(result, dict):
            continue
        for field in (
            "annotations",
            "authors",
            "mesh_headings",
            "publication_types",
            "ranking_reasons",
            "matched_terms",
        ):
            if result.get(field) == []:
                result.pop(field, None)
        for field in ("citations", "rank_features", "coverage_hint", "source_versions"):
            if result.get(field) == {}:
                result.pop(field, None)
    return dumped


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
    raw_authors = _shape_authors(item.get("authors", []))
    include_author_array = response_mode in {"standard", "full"}
    shaped = SearchResult(
        pmid=item.get("pmid", ""),
        title=item.get("title", ""),
        abstract=_inline_abstract(item.get("abstract"))
        if response_mode in {"standard", "full"} or metadata == "with_abstract"
        else None,
        authors=raw_authors if include_author_array else [],
        first_author_et_al=_author_summary(raw_authors),
        journal=item.get("journal"),
        pub_date=item.get("pub_date") or item.get("meta_date_publication") or item.get("date"),
        annotations=item.get("annotations", []) if response_mode == "full" else [],
        score=item.get("score"),
        pmcid=item.get("pmcid"),
        doi=item.get("doi"),
        date=item.get("date"),
        text_hl=_shape_text_hl(item.get("text_hl"), text_hl_format) if include_text_hl else None,
        citations=_shape_citations(item.get("citations"), include_citations),
        recommended_citation=_recommended_citation(item, raw_authors),
        volume=item.get("volume") or item.get("meta_volume"),
        issue=item.get("issue") or item.get("meta_issue"),
        pages=item.get("pages") or item.get("meta_pages"),
        publication_types=item.get("publication_types", []),
        coverage_hint=item.get("coverage_hint"),
        rank_features=rank_features,
        ranking_reasons=rank_features.get("ranking_reasons", []) if rank_features else [],
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

    metadata_authors = _shape_authors(metadata_item.get("authors", []))
    if shaped.first_author_et_al is None:
        shaped.first_author_et_al = _author_summary(metadata_authors)

    basic_fields = (
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
    full_fields = ("authors", *basic_fields, "mesh_headings", "nlm_citation", "bibtex")
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


def _inline_abstract(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if len(normalized) <= INLINE_ABSTRACT_MAX_CHARS:
        return normalized
    return f"{normalized[: INLINE_ABSTRACT_MAX_CHARS - 1].rstrip()}..."


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
            if (
                author.get("display_name")
                and not author.get("last_name")
                and not author.get("fore_name")
                and not author.get("initials")
                and not author.get("collective_name")
            ):
                author = {**author, "collective_name": author["display_name"]}
            shaped.append(PublicationAuthor.model_validate(author))
    return shaped


def _author_summary(authors: list[PublicationAuthor]) -> str | None:
    if not authors:
        return None
    first: str | None = authors[0].display_name or authors[0].collective_name
    if not first:
        return None
    return f"{first} et al." if len(authors) > 1 else first


def _recommended_citation(item: dict[str, Any], authors: list[PublicationAuthor]) -> str | None:
    existing = item.get("recommended_citation")
    if isinstance(existing, str) and existing.strip():
        return existing.strip()
    nlm = item.get("nlm_citation")
    if isinstance(nlm, str) and nlm.strip():
        return nlm.strip()

    parts: list[str] = []
    author_label = _author_summary(authors)
    if author_label:
        parts.append(author_label)
    title = _clean_citation_part(item.get("title"))
    if title:
        parts.append(title)
    journal = _clean_citation_part(item.get("journal"))
    if journal:
        parts.append(journal)
    year = _clean_citation_part(item.get("pub_year") or _citation_year(item))
    if year:
        parts.append(year)
    pmid = _clean_citation_part(item.get("pmid"))
    if pmid:
        parts.append(f"PMID:{pmid}")
    doi = _clean_citation_part(item.get("doi"))
    if doi:
        parts.append(f"doi:{doi}")
    if not parts:
        return None
    return ". ".join(part.rstrip(".") for part in parts) + "."


def _clean_citation_part(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _citation_year(item: dict[str, Any]) -> str | None:
    for key in ("pub_date", "meta_date_publication", "date"):
        text = _clean_citation_part(item.get(key))
        if text:
            match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2})\b", text)
            if match is not None:
                return match.group(1)
    return None


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
    reasons: list[str] = []
    type_boost = 0
    for value in publication_types:
        for term in sorted(GUIDELINE_TYPES, key=len, reverse=True):
            if term in value:
                type_boost += 3
                reasons.append(term)
                break
    term_boost = 0
    for term in GUIDELINE_TERMS:
        if term in title or term in abstract:
            term_boost += 1
            reasons.append("systematic review" if term == "systematic-review" else term)
    return {
        "guideline_boost": type_boost + term_boost,
        "ranking_reasons": list(dict.fromkeys(reasons)),
    }
