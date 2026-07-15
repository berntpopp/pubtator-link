"""Normalize PubTator PMC identifiers and classify usable full-text documents."""

from __future__ import annotations

import re
from typing import Any, Literal

from pubtator_link.api.client import PubTatorAPIError
from pubtator_link.mcp.input_normalization import InputNormalizationError
from pubtator_link.models.responses import PublicationExportResponse

_PMCID = re.compile(r"^PMC(?P<number>[1-9][0-9]*)$")


def canonical_pmcid(value: str) -> str:
    """Return a canonical PMCID or reject input that is not a PMC identifier."""

    candidate = value.strip().upper()
    match = _PMCID.fullmatch(candidate)
    if match is None:
        raise ValueError("pmcids must contain canonical PMC IDs such as PMC11223843")
    return f"PMC{match.group('number')}"


def _canonical_requested_pmcids(pmcids: list[str]) -> list[str]:
    try:
        return list(dict.fromkeys(canonical_pmcid(pmcid) for pmcid in pmcids))
    except ValueError as exc:
        raise InputNormalizationError(
            field_errors=[
                {
                    "field": "pmcids",
                    "reason": "Each value must be a canonical PMC ID such as PMC11223843.",
                }
            ],
            recovery_hint="Provide PMC IDs in the form PMC11223843.",
        ) from exc


def canonical_document_id(value: object) -> str | None:
    """Normalize a PubTator document identifier without stringifying arbitrary objects."""

    if isinstance(value, bool) or not isinstance(value, str | int):
        return None
    text = str(value).strip().upper()
    if text.isdigit():
        return f"PMC{text}"
    return text if _PMCID.fullmatch(text) else None


def has_meaningful_pmc_content(document: dict[str, Any]) -> bool:
    """Identify a document with actual text or annotation content."""

    if any(bool(document.get(key)) for key in ("passages", "annotations", "relations")):
        return True
    return bool(str(document.get("text") or "").strip())


def classify_pmc_documents(
    requested: list[str], documents: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return requested meaningful documents and the requested IDs still unavailable."""

    meaningful_by_id: dict[str, dict[str, Any]] = {}
    for document in documents:
        document_id = canonical_document_id(document.get("id"))
        if document_id and document_id in requested and has_meaningful_pmc_content(document):
            meaningful_by_id.setdefault(document_id, {**document, "id": document_id})
    found = [meaningful_by_id[pmcid] for pmcid in requested if pmcid in meaningful_by_id]
    unavailable = [pmcid for pmcid in requested if pmcid not in meaningful_by_id]
    return found, unavailable


def pmc_not_found_envelope(unavailable_pmcids: list[str]) -> dict[str, Any]:
    """Return a fixed, non-retryable error without exposing upstream prose."""

    if len(unavailable_pmcids) == 1:
        message = f"No PubTator full text is available for PMCID {unavailable_pmcids[0]}."
    else:
        message = "No PubTator full text is available for the requested PMCIDs."
    payload: dict[str, Any] = {
        "success": False,
        "error_code": "not_found",
        "message": message,
        "retryable": False,
        "fallback_tool": None,
        "fallback_args": None,
        "recovery_action": "Provide a PMCID with available PubTator full text.",
        "_meta": {
            "next_commands": [{"tool": "diagnostics", "arguments": {}}],
            "unsafe_for_clinical_use": True,
        },
    }
    if len(unavailable_pmcids) > 1:
        payload["unavailable_pmcids"] = unavailable_pmcids
    return payload


async def fetch_pmc_annotations_impl(
    *,
    service: Any,
    pmcids: list[str],
    format: Literal["biocxml", "biocjson"] = "biocjson",
) -> dict[str, Any]:
    """Fetch only requested PMC documents with meaningful PubTator full text."""

    canonical_pmcids = _canonical_requested_pmcids(pmcids)
    try:
        result = await service.export_pmc_publications_list(
            pmcids=canonical_pmcids,
            format=format,
        )
    except PubTatorAPIError as exc:
        if exc.status_code in {400, 404}:
            return pmc_not_found_envelope(canonical_pmcids)
        raise
    documents = [
        document.model_dump() if hasattr(document, "model_dump") else dict(document)
        for document in result.documents
    ]
    found_documents, unavailable_pmcids = classify_pmc_documents(canonical_pmcids, documents)
    if unavailable_pmcids:
        return pmc_not_found_envelope(unavailable_pmcids)
    return PublicationExportResponse(
        format=result.format,
        pmcids=canonical_pmcids,
        full_text=True,
        export_data={"documents": found_documents},
        count=len(found_documents),
        coverage_by_pmcid=dict.fromkeys(canonical_pmcids, "full_text"),
        coverage_reason_by_pmcid=dict.fromkeys(canonical_pmcids, "full_text_available"),
    ).model_dump()
