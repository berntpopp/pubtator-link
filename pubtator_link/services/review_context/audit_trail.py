from __future__ import annotations

from typing import Any

from pubtator_link.models.review_rerag import (
    ReviewAuditTrailItem,
    ReviewAuditTrailResponse,
    ReviewPassageLookupResponse,
    stable_citation_key_for_passage,
)


async def latest_audit_passage_ids(
    repository: Any, *, review_id: str, session_id: str | None
) -> list[str]:
    get_latest = getattr(repository, "get_latest_llm_context", None)
    if get_latest is None:
        return []
    context = await get_latest(review_id, session_id=session_id)
    if context is None:
        return []
    audit_ids = list(getattr(context, "audit_passage_ids", None) or [])
    if audit_ids:
        return audit_ids
    return list(getattr(context, "selected_passage_ids", None) or [])


def audit_trail_response(
    *,
    review_id: str,
    session_id: str | None,
    lookup: ReviewPassageLookupResponse,
    max_chars_per_passage: int,
) -> ReviewAuditTrailResponse:
    items: list[ReviewAuditTrailItem] = []
    lines: list[str] = []
    for passage in lookup.passages:
        quote = (
            passage.quote.text
            if passage.quote is not None
            else passage.text[:max_chars_per_passage]
        )
        stable_key = passage.stable_citation_key or stable_citation_key_for_passage(
            passage.passage_id
        )
        item = ReviewAuditTrailItem(
            pmid=passage.pmid,
            pmcid=passage.pmcid,
            passage_id=passage.passage_id,
            stable_citation_key=stable_key,
            section=passage.section,
            quote=quote,
            char_count=len(quote),
        )
        items.append(item)
        pmid_text = f"PMID {passage.pmid}" if passage.pmid else "PMID unavailable"
        lines.append(f"- {stable_key} {pmid_text} {passage.passage_id} {passage.section}: {quote}")
    return ReviewAuditTrailResponse(
        review_id=review_id,
        session_id=session_id,
        items=items,
        not_found=lookup.not_found,
        audit_block="\n".join(lines),
    )
