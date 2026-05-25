from __future__ import annotations

from typing import Any, TypedDict


class PmcExportCoverage(TypedDict):
    coverage_by_pmcid: dict[str, str]
    coverage_reason_by_pmcid: dict[str, str]


def pmc_export_coverage(
    pmcids: list[str],
    documents: list[dict[str, Any]],
) -> PmcExportCoverage:
    documents_by_id = {str(document.get("id") or ""): document for document in documents}
    coverage: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for pmcid in pmcids:
        document = documents_by_id.get(pmcid)
        if _has_pmc_content(document):
            coverage[pmcid] = "full_text"
            reasons[pmcid] = "full_text_available"
        else:
            coverage[pmcid] = "unknown"
            reasons[pmcid] = "no_pmc_full_text_retrievable"
    return {"coverage_by_pmcid": coverage, "coverage_reason_by_pmcid": reasons}


def _has_pmc_content(document: dict[str, Any] | None) -> bool:
    if not document:
        return False
    for field in ("passages", "annotations", "relations"):
        value = document.get(field)
        if isinstance(value, list) and value:
            return True
    text = document.get("text")
    return isinstance(text, str) and bool(text.strip())
