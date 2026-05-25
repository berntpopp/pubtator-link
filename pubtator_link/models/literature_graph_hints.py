"""Caller-facing hints derived from literature graph models."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, Literal

RelatedEvidenceMetadataStatus = Literal["success", "partial", "timeout", "unavailable"]


def related_metadata_status(provider_status: Sequence[Any]) -> RelatedEvidenceMetadataStatus:
    """Summarize candidate metadata enrichment status for callers."""
    for status in provider_status:
        if (
            getattr(status, "provider", None) != "pubmed_metadata"
            or getattr(status, "operation", None) != "candidate_metadata"
        ):
            continue
        status_value = getattr(status, "status", None)
        if status_value == "success":
            return "success"
        if status_value == "partial":
            return "partial"
        message = str(getattr(status, "message", "") or "").casefold()
        if "timed out" in message or "timeout" in message:
            return "timeout"
        return "unavailable"
    return "unavailable"


def graph_freshness_note(response: Any) -> str | None:
    """Explain empty graph results for recent papers when providers had no usable data."""
    source = getattr(response, "source", None)
    references = getattr(response, "references", ())
    cited_by = getattr(response, "cited_by", ())
    provider_status = getattr(response, "provider_status", ())
    if references or cited_by:
        return None
    if not _recent_publication(source):
        return None
    if not _no_usable_graph(provider_status):
        return None
    age_note = _approximate_age_note(getattr(source, "year", None))
    if age_note:
        return (
            "Citation graph providers typically lag for new papers; "
            f"this publication is {age_note}."
        )
    return "Citation graph providers typically lag for new papers."


def _recent_publication(source: Any) -> bool:
    year = getattr(source, "year", None)
    return isinstance(year, int) and 0 <= date.today().year - year <= 2


def _no_usable_graph(provider_status: Sequence[Any]) -> bool:
    checked = False
    for status in provider_status:
        if getattr(status, "operation", None) not in {"references", "cited_by"}:
            continue
        status_value = getattr(status, "status", None)
        result_count = int(getattr(status, "result_count", 0) or 0)
        if status_value in {"success", "partial"} and result_count > 0:
            return False
        if status_value in {"empty", "failed", "skipped", "disabled"}:
            checked = True
    return checked


def _approximate_age_note(year: Any) -> str | None:
    if not isinstance(year, int):
        return None
    age = date.today().year - year
    if age <= 0:
        return "less than 1 year old"
    if age == 1:
        return "about 1 year old"
    return f"about {age} years old"
