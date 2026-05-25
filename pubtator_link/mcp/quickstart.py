from __future__ import annotations

import hashlib
import re
from typing import Any

from pubtator_link.models.review_rerag import IndexReviewEvidenceRequest


def quickstart_selected_pmids(manifest: Any) -> list[str]:
    return [candidate.pmid for candidate in manifest.candidates if candidate.pmid]


def query_length_warning(query: str) -> str | None:
    if len(query.split()) <= 18:
        return None
    return "Long natural-language question used for search; consider splitting into 6 or fewer key terms."


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
