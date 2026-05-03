"""Citation graph orchestration service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from pubtator_link.models.literature_graph import (
    LiteratureAvailability,
    LiteratureGraphResponseMeta,
    LiteraturePaper,
    ProviderWarning,
    PublicationCitationGraphRequest,
    PublicationCitationGraphResponse,
    dedupe_papers,
)
from pubtator_link.models.publication_metadata import PublicationMetadataRequest
from pubtator_link.services.literature_providers import (
    CROSSREF_PROVIDER,
    EUROPE_PMC_PROVIDER,
    OPENALEX_PROVIDER,
    UNPAYWALL_PROVIDER,
)


class CrossrefProvider(Protocol):
    """Crossref behavior needed by the citation graph service."""

    async def get_work(self, doi: str) -> Mapping[str, Any]:
        """Fetch a Crossref work by DOI."""

    def references_from_work(self, work: Mapping[str, Any]) -> list[LiteraturePaper]:
        """Map a Crossref work payload into reference papers."""


class EuropePmcCitationProvider(Protocol):
    """Europe PMC citation behavior needed by the citation graph service."""

    async def get_citations(self, pmid: str, *, limit: int) -> list[LiteraturePaper]:
        """Fetch papers citing the PMID."""


class OpenAlexCitationProvider(Protocol):
    """OpenAlex citation fallback behavior needed by the citation graph service."""

    async def get_references(self, doi: str, *, limit: int) -> list[LiteraturePaper]:
        """Fetch referenced works for a DOI."""

    async def get_cited_by(self, doi: str, *, limit: int) -> list[LiteraturePaper]:
        """Fetch citing works for a DOI."""


class OpenAccessProvider(Protocol):
    """Open access enrichment behavior for DOI-bearing graph papers."""

    async def get_oa_status(self, doi: str) -> LiteratureAvailability | ProviderWarning:
        """Fetch open access status for a DOI."""


class CitationGraphService:
    """Build citation-neighbor responses from literature providers."""

    def __init__(
        self,
        *,
        crossref: CrossrefProvider | None = None,
        europe_pmc: EuropePmcCitationProvider | None = None,
        openalex: OpenAlexCitationProvider | None = None,
        unpaywall: OpenAccessProvider | None = None,
        discovery_service: Any | None = None,
        metadata_service: Any | None = None,
    ) -> None:
        self.crossref = crossref
        self.europe_pmc = europe_pmc
        self.openalex = openalex
        self.unpaywall = unpaywall
        self.discovery_service = discovery_service
        self.metadata_service = metadata_service

    async def get_citation_graph(
        self, request: PublicationCitationGraphRequest
    ) -> PublicationCitationGraphResponse:
        """Return citation neighbors for one PMID or DOI source."""
        warnings: list[ProviderWarning] = []
        source = await self._source_paper(request)
        references: list[LiteraturePaper] = []
        cited_by: list[LiteraturePaper] = []

        if request.doi and not source.pmid and request.direction in {"both", "cited_by"}:
            warnings.append(
                ProviderWarning(
                    provider="identifier_resolution",
                    status="partial_identifier_resolution",
                    retryable=False,
                    message=(
                        "DOI source did not resolve to a PMID; PMID-only cited-by providers "
                        "may be skipped."
                    ),
                )
            )

        if request.direction in {"references", "both"} and source.doi and self.crossref:
            try:
                work = await self.crossref.get_work(source.doi)
                references.extend(self.crossref.references_from_work(work))
            except Exception as exc:  # pragma: no cover - exercised by provider fakes as needed
                warnings.append(_provider_failed_warning(CROSSREF_PROVIDER, exc))

        if request.direction in {"references", "both"} and source.doi and self.openalex:
            try:
                references.extend(
                    await self.openalex.get_references(source.doi, limit=request.max_results)
                )
            except Exception as exc:
                warnings.append(_provider_failed_warning(OPENALEX_PROVIDER, exc))

        if request.direction in {"cited_by", "both"} and self.europe_pmc and source.pmid:
            try:
                cited_by.extend(
                    await self.europe_pmc.get_citations(source.pmid, limit=request.max_results)
                )
            except Exception as exc:
                warnings.append(_provider_failed_warning(EUROPE_PMC_PROVIDER, exc))

        if request.direction in {"cited_by", "both"} and source.doi and self.openalex:
            try:
                cited_by.extend(
                    await self.openalex.get_cited_by(source.doi, limit=request.max_results)
                )
            except Exception as exc:
                warnings.append(_provider_failed_warning(OPENALEX_PROVIDER, exc))

        references = dedupe_papers(references)[: request.max_results]
        cited_by = dedupe_papers(cited_by)[: request.max_results]
        if request.include_open_access_status:
            references = await self._with_open_access_status(references, warnings)
            cited_by = await self._with_open_access_status(cited_by, warnings)
        candidate_pmids = _candidate_pmids([*references, *cited_by])
        return PublicationCitationGraphResponse(
            source=source,
            references=references,
            cited_by=cited_by,
            candidate_pmids=candidate_pmids,
            metadata_only=_metadata_only([*references, *cited_by]),
            _meta=LiteratureGraphResponseMeta(
                warnings=warnings,
                next_commands=_next_commands(candidate_pmids),
            ),
        )

    async def _source_paper(self, request: PublicationCitationGraphRequest) -> LiteraturePaper:
        if request.pmid:
            if request.resolve_metadata:
                metadata = await self._metadata_for_pmid(request.pmid)
                if metadata is not None:
                    return LiteraturePaper(
                        pmid=metadata.pmid,
                        doi=metadata.doi,
                        pmcid=metadata.pmcid,
                        title=metadata.title,
                        journal=metadata.journal,
                        year=metadata.pub_year,
                        publication_types=metadata.publication_types,
                    )
            return LiteraturePaper(pmid=request.pmid)
        if request.doi:
            pmid = await self._pmid_for_doi(request.doi)
            if pmid is not None:
                if request.resolve_metadata:
                    metadata = await self._metadata_for_pmid(pmid)
                    if metadata is not None:
                        return LiteraturePaper(
                            pmid=metadata.pmid,
                            doi=metadata.doi or request.doi,
                            pmcid=metadata.pmcid,
                            title=metadata.title,
                            journal=metadata.journal,
                            year=metadata.pub_year,
                            publication_types=metadata.publication_types,
                        )
                return LiteraturePaper(pmid=pmid, doi=request.doi)
            return LiteraturePaper(doi=request.doi)
        raise ValueError("exactly one of pmid or doi is required")

    async def _pmid_for_doi(self, doi: str) -> str | None:
        if self.discovery_service is None:
            return None
        try:
            records = await self.discovery_service.convert_article_ids([doi], source="doi")
        except Exception:
            return None
        if hasattr(records, "records"):
            records = records.records
        for record in records:
            pmid = getattr(record, "pmid", None)
            if pmid:
                return str(pmid)
        return None

    async def _metadata_for_pmid(self, pmid: str) -> Any | None:
        if self.metadata_service is None:
            return None
        try:
            response = await self.metadata_service.get_metadata(
                PublicationMetadataRequest(
                    pmids=[pmid],
                    include_mesh=False,
                    include_publication_types=True,
                    include_citations="none",
                    include_coverage=True,
                )
            )
        except Exception:
            return None
        metadata = getattr(response, "metadata", [])
        if not metadata:
            return None
        return metadata[0]

    async def _with_open_access_status(
        self,
        papers: list[LiteraturePaper],
        warnings: list[ProviderWarning],
    ) -> list[LiteraturePaper]:
        if self.unpaywall is None:
            return papers
        enriched: list[LiteraturePaper] = []
        for paper in papers:
            if not paper.doi:
                enriched.append(paper)
                continue
            try:
                availability = await self.unpaywall.get_oa_status(paper.doi)
            except Exception as exc:
                warnings.append(_provider_failed_warning(UNPAYWALL_PROVIDER, exc))
                enriched.append(paper)
                continue
            if isinstance(availability, ProviderWarning):
                warnings.append(availability)
                enriched.append(paper)
                continue
            enriched.append(_paper_with_availability(paper, availability))
        return enriched


def _provider_failed_warning(provider: str, exc: Exception) -> ProviderWarning:
    return ProviderWarning(
        provider=provider,
        status="provider_failed",
        retryable=True,
        message=f"{provider} citation lookup failed: {exc}",
    )


def _paper_with_availability(
    paper: LiteraturePaper,
    availability: LiteratureAvailability,
) -> LiteraturePaper:
    merged = paper.availability.model_copy(
        update={
            "has_pmc_full_text": (
                paper.availability.has_pmc_full_text or availability.has_pmc_full_text
            ),
            "is_open_access": paper.availability.is_open_access or availability.is_open_access,
            "has_pdf": paper.availability.has_pdf or availability.has_pdf,
            "full_text_url": paper.availability.full_text_url or availability.full_text_url,
            "oa_status": paper.availability.oa_status or availability.oa_status,
            "license_or_access_hint": paper.availability.license_or_access_hint
            or availability.license_or_access_hint,
        }
    )
    status = (
        "resolved_full_text_candidate"
        if merged.has_pmc_full_text or merged.is_open_access or merged.full_text_url
        else paper.status
    )
    return paper.model_copy(update={"availability": merged, "status": status})


def _candidate_pmids(papers: Sequence[LiteraturePaper]) -> list[str]:
    seen: set[str] = set()
    pmids: list[str] = []
    for paper in papers:
        if paper.pmid and paper.pmid not in seen:
            seen.add(paper.pmid)
            pmids.append(paper.pmid)
    return pmids


def _metadata_only(papers: Sequence[LiteraturePaper]) -> list[LiteraturePaper]:
    metadata_statuses = {
        "resolved_metadata_only",
        "unresolved_reference",
        "publisher_entitlement_required",
    }
    return [paper for paper in dedupe_papers(list(papers)) if paper.status in metadata_statuses]


def _next_commands(candidate_pmids: list[str]) -> list[dict[str, Any]]:
    if not candidate_pmids:
        return []
    return [
        {
            "tool": "pubtator.get_publication_passages",
            "arguments": {"pmids": candidate_pmids},
        },
        {
            "tool": "pubtator.index_review_evidence",
            "arguments": {"pmids": candidate_pmids, "prepare_mode": "selected"},
        },
    ]
