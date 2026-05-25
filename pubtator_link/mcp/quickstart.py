from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable
from typing import Any

from pubtator_link.models.review_rerag import IndexReviewEvidenceRequest

_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "best",
    "considering",
    "for",
    "in",
    "of",
    "the",
    "what",
    "when",
    "with",
}


def quickstart_selected_pmids(manifest: Any) -> list[str]:
    return [candidate.pmid for candidate in manifest.candidates if candidate.pmid]


def query_length_warning(query: str) -> str | None:
    if len(query.split()) <= 18:
        return None
    return "Long natural-language question used for search; consider splitting into 6 or fewer key terms."


def query_variants_for_question(question: str) -> list[str]:
    variants = [question]
    words = re.findall(r"[A-Za-z0-9@_-]+", question)
    if len(words) <= 18:
        return variants
    keywords = [word for word in words if word.lower() not in _QUERY_STOPWORDS and len(word) > 2][
        :8
    ]
    shortened = " ".join(keywords)
    if shortened and shortened.lower() != question.lower():
        variants.append(shortened)
    anchors = _biomedical_query_anchors(words)
    if len(anchors) >= 2:
        _append_query_variant(variants, " ".join(anchors[:3]))
        _append_query_variant(variants, " ".join(anchors[:6]))
    return variants


def _biomedical_query_anchors(words: list[str]) -> list[str]:
    lowered = {word.lower() for word in words}
    anchors: list[str] = []
    for word in words:
        if re.fullmatch(r"@?[A-Z][A-Z0-9_-]{1,15}", word):
            _append_query_variant(anchors, word)
    if "fmf" in lowered or "familial" in lowered:
        _append_query_variant(anchors, "FMF")
    for term in ("colchicine", "treatment", "therapy"):
        if term in lowered:
            _append_query_variant(anchors, term)
    if lowered & {"child", "children", "pediatric", "paediatric", "juvenile"}:
        _append_query_variant(anchors, "pediatric")
    for term in ("diagnosis", "monitoring"):
        if term in lowered:
            _append_query_variant(anchors, term)
    if lowered & {"vus", "uncertain"}:
        _append_query_variant(anchors, "VUS")
    if "variant" in lowered or "variants" in lowered:
        _append_query_variant(anchors, "variant")
    return anchors


def _append_query_variant(variants: list[str], query: str) -> None:
    if query and all(query.lower() != existing.lower() for existing in variants):
        variants.append(query)


def selected_pmids_from_search_result(search_result: dict[str, Any], max_pmids: int) -> list[str]:
    selected_pmids: list[str] = []
    for item in search_result.get("results", []):
        if not isinstance(item, dict):
            continue
        pmid = str(item.get("pmid") or "").strip()
        if pmid and pmid not in selected_pmids:
            selected_pmids.append(pmid)
        if len(selected_pmids) >= max_pmids:
            break
    return selected_pmids


async def search_pmids_for_query_variants(
    question: str,
    *,
    max_pmids: int,
    search: Callable[[str], Awaitable[dict[str, Any]]],
) -> tuple[dict[str, Any], list[str], list[str]]:
    search_result: dict[str, Any] = {}
    selected_pmids: list[str] = []
    attempted: list[str] = []
    for search_query in query_variants_for_question(question):
        attempted.append(search_query)
        search_result = await search(search_query)
        selected_pmids = selected_pmids_from_search_result(search_result, max_pmids)
        if selected_pmids:
            break
    return search_result, selected_pmids, attempted


def quickstart_review_id(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:48]
    if not slug:
        slug = "review"
    digest = hashlib.sha256(topic.encode("utf-8")).hexdigest()[:8]
    return f"quickstart-{slug}-{digest}"


def review_indexing_service_from_factory(factory: Any, queue: Any) -> Any:
    try:
        return factory(repository=queue.repository, queue=queue)
    except TypeError:
        try:
            return factory(queue)
        except TypeError:
            return factory(queue=queue)


async def wait_for_quickstart_index(
    *,
    review_id: str,
    session_id: str,
    pmids: list[str],
    stage_service: Any,
    timeout_ms: int,
    review_indexing_service_factory: Any,
) -> None:
    if not pmids:
        return
    queue = getattr(stage_service, "queue", None)
    if queue is None:
        return
    indexing_service = review_indexing_service_from_factory(review_indexing_service_factory, queue)
    await indexing_service.index_review_evidence(
        review_id,
        IndexReviewEvidenceRequest(
            pmids=pmids,
            session_id=session_id,
            wait_for_completion=True,
            wait_for_status="complete_or_partial",
            timeout_ms=timeout_ms,
        ),
    )
