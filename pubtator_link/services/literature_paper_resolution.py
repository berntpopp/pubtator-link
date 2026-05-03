"""Shared LiteraturePaper mapping and availability merge helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pubtator_link.models.literature_graph import (
    LiteratureAuthor,
    LiteratureAvailability,
    LiteratureGraphProvenance,
    LiteraturePaper,
    LiteraturePaperStatus,
)


def paper_from_publication_metadata(
    metadata: Any,
    *,
    include_authors: bool = False,
    availability: LiteratureAvailability | None = None,
) -> LiteraturePaper:
    """Map publication metadata into a graph paper without conflating PMCID and OA."""
    has_pmc_full_text = getattr(metadata, "coverage", None) == "full_text" or bool(
        getattr(metadata, "pmcid", None)
    )
    merged_availability = LiteratureAvailability(
        has_pmc_full_text=has_pmc_full_text,
        is_open_access=False,
    )
    if availability is not None:
        merged_availability = _merge_availability_values(merged_availability, availability)
    status: LiteraturePaperStatus = (
        "resolved_full_text_candidate"
        if _has_full_text_signal(merged_availability)
        else "resolved_metadata_only"
    )
    return LiteraturePaper(
        pmid=getattr(metadata, "pmid", None),
        doi=getattr(metadata, "doi", None),
        pmcid=getattr(metadata, "pmcid", None),
        title=getattr(metadata, "title", None),
        journal=getattr(metadata, "journal", None),
        year=getattr(metadata, "pub_year", None),
        publication_types=list(getattr(metadata, "publication_types", []) or []),
        authors=_authors_from_metadata(metadata) if include_authors else [],
        availability=merged_availability,
        status=status,
        provenance=[LiteratureGraphProvenance(provider="pubmed_metadata")],
    )


def merge_literature_availability(
    primary: LiteraturePaper,
    fallback: LiteraturePaper,
) -> LiteraturePaper:
    """Merge missing paper fields while preserving independent availability signals."""
    availability = _merge_availability_values(primary.availability, fallback.availability)
    return primary.model_copy(
        update={
            "doi": primary.doi or fallback.doi,
            "pmcid": primary.pmcid or fallback.pmcid,
            "openalex_id": primary.openalex_id or fallback.openalex_id,
            "title": primary.title or fallback.title,
            "journal": primary.journal or fallback.journal,
            "year": primary.year or fallback.year,
            "publication_types": primary.publication_types or fallback.publication_types,
            "authors": primary.authors or fallback.authors,
            "availability": availability,
            "status": best_literature_status(primary, fallback, availability),
            "provenance": [*primary.provenance, *fallback.provenance],
        }
    )


def best_literature_status(
    primary: LiteraturePaper,
    fallback: LiteraturePaper,
    availability: LiteratureAvailability | None = None,
) -> LiteraturePaperStatus:
    """Return the strongest status implied by two papers and their availability."""
    merged = availability or _merge_availability_values(primary.availability, fallback.availability)
    if (
        _has_full_text_signal(merged)
        or primary.status == "resolved_full_text_candidate"
        or fallback.status == "resolved_full_text_candidate"
    ):
        return "resolved_full_text_candidate"
    if primary.status == "resolved_metadata_only" or fallback.status == "resolved_metadata_only":
        return "resolved_metadata_only"
    if primary.status == "publisher_entitlement_required":
        return primary.status
    return fallback.status


def deduped_signals(*groups: Iterable[str]) -> list[str]:
    """Return ordered unique LLM-facing signals."""
    signals: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for signal in group:
            if signal and signal not in seen:
                seen.add(signal)
                signals.append(signal)
    return signals


def _merge_availability_values(
    primary: LiteratureAvailability,
    fallback: LiteratureAvailability,
) -> LiteratureAvailability:
    return primary.model_copy(
        update={
            "has_pmc_full_text": primary.has_pmc_full_text or fallback.has_pmc_full_text,
            "is_open_access": primary.is_open_access or fallback.is_open_access,
            "has_pdf": primary.has_pdf or fallback.has_pdf,
            "full_text_url": primary.full_text_url or fallback.full_text_url,
            "oa_status": primary.oa_status or fallback.oa_status,
            "license_or_access_hint": primary.license_or_access_hint
            or fallback.license_or_access_hint,
        }
    )


def _has_full_text_signal(availability: LiteratureAvailability) -> bool:
    return (
        availability.has_pmc_full_text
        or availability.is_open_access
        or bool(availability.full_text_url)
    )


def _authors_from_metadata(metadata: Any) -> list[LiteratureAuthor]:
    return [
        LiteratureAuthor(name=author.display_name)
        for author in getattr(metadata, "authors", []) or []
        if getattr(author, "display_name", "")
    ]
