from __future__ import annotations

from typing import Literal, Protocol

from pubtator_link.models.responses import SearchResponse
from pubtator_link.models.review_rerag import SourceCoverageHint

SearchCoverageMode = Literal["none", "preflight"]


class SearchCoveragePreflight(Protocol):
    """Service capable of estimating source coverage for search PMIDs."""

    async def preflight_pmids(self, pmids: list[str]) -> list[SourceCoverageHint]: ...


async def attach_preflight_coverage(
    response: SearchResponse,
    preflight_service: SearchCoveragePreflight,
) -> None:
    """Attach per-result source coverage hints, degrading without failing search."""
    pmids = [result.pmid for result in response.results if result.pmid]
    if not pmids:
        return

    try:
        hints = await preflight_service.preflight_pmids(pmids)
    except Exception:
        response.message = (
            "Coverage preflight failed; search results returned without coverage hints."
        )
        response.source_versions["coverage_preflight"] = "failed"
        return

    hints_by_pmid = {hint.pmid: hint.model_dump(mode="json") for hint in hints}
    for result in response.results:
        result.coverage_hint = hints_by_pmid.get(result.pmid)
    response.source_versions["coverage_preflight"] = "included"
