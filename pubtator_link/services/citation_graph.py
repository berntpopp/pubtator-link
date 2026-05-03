"""Citation graph orchestration service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from pubtator_link.models.literature_graph import (
    LiteratureAvailability,
    LiteratureCandidateSummary,
    LiteratureGraphResponseMeta,
    LiteraturePaper,
    LiteratureProviderStatus,
    LiteratureProviderStatusValue,
    ProviderWarning,
    PublicationCitationGraphRequest,
    PublicationCitationGraphResponse,
    dedupe_papers,
)
from pubtator_link.models.publication_metadata import PublicationMetadataRequest
from pubtator_link.services.literature_graph_compact import candidate_summary
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
        references_status: list[LiteratureProviderStatus] = []
        cited_by_status: list[LiteratureProviderStatus] = []
        identifier_resolution_status: list[LiteratureProviderStatus] = []
        open_access_status: list[LiteratureProviderStatus] = []

        if request.doi and not source.pmid:
            if request.direction in {"both", "cited_by"}:
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
            identifier_resolution_status.append(
                LiteratureProviderStatus(
                    provider="identifier_resolution",
                    operation="doi_to_pmid",
                    status="empty",
                    result_count=0,
                    message="DOI source did not resolve to a PMID.",
                )
            )
        elif request.doi and source.pmid:
            identifier_resolution_status.append(
                LiteratureProviderStatus(
                    provider="identifier_resolution",
                    operation="doi_to_pmid",
                    status="success",
                    result_count=1,
                )
            )

        if self.crossref and request.direction not in {"references", "both"}:
            references_status.append(
                _provider_status(CROSSREF_PROVIDER, "references", "not_requested")
            )
        if request.direction in {"references", "both"} and not source.doi and self.crossref:
            references_status.append(
                _provider_status(
                    CROSSREF_PROVIDER,
                    "references",
                    "skipped",
                    message="DOI required",
                )
            )
        if request.direction in {"references", "both"} and source.doi and self.crossref:
            try:
                work = await self.crossref.get_work(source.doi)
                records = self.crossref.references_from_work(work)
                references.extend(records)
                references_status.append(
                    _provider_status(
                        CROSSREF_PROVIDER,
                        "references",
                        "success" if records else "empty",
                        len(records),
                    )
                )
            except Exception as exc:  # pragma: no cover - exercised by provider fakes as needed
                warnings.append(_provider_failed_warning(CROSSREF_PROVIDER, exc))
                references_status.append(
                    _provider_status(
                        CROSSREF_PROVIDER,
                        "references",
                        "failed",
                        retryable=True,
                        message=str(exc),
                    )
                )

        if self.openalex and request.direction not in {"references", "both"}:
            references_status.append(
                _provider_status(OPENALEX_PROVIDER, "references", "not_requested")
            )
        if request.direction in {"references", "both"} and not source.doi and self.openalex:
            references_status.append(
                _provider_status(
                    OPENALEX_PROVIDER,
                    "references",
                    "skipped",
                    message="DOI required",
                )
            )
        if request.direction in {"references", "both"} and source.doi and self.openalex:
            try:
                records = await self.openalex.get_references(source.doi, limit=request.max_results)
                references.extend(records)
                references_status.append(
                    _provider_status(
                        OPENALEX_PROVIDER,
                        "references",
                        "success" if records else "empty",
                        len(records),
                    )
                )
            except Exception as exc:
                warnings.append(_provider_failed_warning(OPENALEX_PROVIDER, exc))
                references_status.append(
                    _provider_status(
                        OPENALEX_PROVIDER,
                        "references",
                        "failed",
                        retryable=True,
                        message=str(exc),
                    )
                )

        if self.europe_pmc and request.direction not in {"cited_by", "both"}:
            cited_by_status.append(
                _provider_status(EUROPE_PMC_PROVIDER, "cited_by", "not_requested")
            )
        if request.direction in {"cited_by", "both"} and self.europe_pmc and not source.pmid:
            cited_by_status.append(
                _provider_status(
                    EUROPE_PMC_PROVIDER,
                    "cited_by",
                    "skipped",
                    message="PMID required",
                )
            )
        if request.direction in {"cited_by", "both"} and self.europe_pmc and source.pmid:
            try:
                records = await self.europe_pmc.get_citations(
                    source.pmid,
                    limit=request.max_results,
                )
                cited_by.extend(records)
                cited_by_status.append(
                    _provider_status(
                        EUROPE_PMC_PROVIDER,
                        "cited_by",
                        "success" if records else "empty",
                        len(records),
                    )
                )
            except Exception as exc:
                warnings.append(_provider_failed_warning(EUROPE_PMC_PROVIDER, exc))
                cited_by_status.append(
                    _provider_status(
                        EUROPE_PMC_PROVIDER,
                        "cited_by",
                        "failed",
                        retryable=True,
                        message=str(exc),
                    )
                )

        if self.openalex and request.direction not in {"cited_by", "both"}:
            cited_by_status.append(_provider_status(OPENALEX_PROVIDER, "cited_by", "not_requested"))
        if request.direction in {"cited_by", "both"} and not source.doi and self.openalex:
            cited_by_status.append(
                _provider_status(
                    OPENALEX_PROVIDER,
                    "cited_by",
                    "skipped",
                    message="DOI required",
                )
            )
        if request.direction in {"cited_by", "both"} and source.doi and self.openalex:
            try:
                records = await self.openalex.get_cited_by(source.doi, limit=request.max_results)
                cited_by.extend(records)
                cited_by_status.append(
                    _provider_status(
                        OPENALEX_PROVIDER,
                        "cited_by",
                        "success" if records else "empty",
                        len(records),
                    )
                )
            except Exception as exc:
                warnings.append(_provider_failed_warning(OPENALEX_PROVIDER, exc))
                cited_by_status.append(
                    _provider_status(
                        OPENALEX_PROVIDER,
                        "cited_by",
                        "failed",
                        retryable=True,
                        message=str(exc),
                    )
                )

        references = dedupe_papers(references)[: request.max_results]
        cited_by = dedupe_papers(cited_by)[: request.max_results]
        if request.include_open_access_status:
            references = await self._with_open_access_status(
                references,
                warnings,
                open_access_status,
            )
            cited_by = await self._with_open_access_status(
                cited_by,
                warnings,
                open_access_status,
            )
        candidate_pmids = _candidate_pmids([*references, *cited_by])
        reference_candidates = _citation_candidates(references, "source_reference")
        cited_by_candidates = _citation_candidates(cited_by, "source_cited_by")
        response_references = [] if request.response_mode == "compact" else references
        response_cited_by = [] if request.response_mode == "compact" else cited_by
        response_metadata_only = (
            [] if request.response_mode == "compact" else _metadata_only([*references, *cited_by])
        )
        if not request.include_provider_status:
            references_status = []
            cited_by_status = []
            identifier_resolution_status = []
            open_access_status = []
        return PublicationCitationGraphResponse(
            source=source,
            references=response_references,
            cited_by=response_cited_by,
            response_mode=request.response_mode,
            reference_candidates=reference_candidates,
            cited_by_candidates=cited_by_candidates,
            candidate_pmids=candidate_pmids,
            metadata_only=response_metadata_only,
            references_status=references_status,
            cited_by_status=cited_by_status,
            identifier_resolution_status=identifier_resolution_status,
            open_access_status=open_access_status,
            _meta=LiteratureGraphResponseMeta(
                response_mode=request.response_mode,
                warnings=warnings,
                next_commands=_next_commands(candidate_pmids),
                provider_status=[
                    *references_status,
                    *cited_by_status,
                    *identifier_resolution_status,
                    *open_access_status,
                ],
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
        open_access_status: list[LiteratureProviderStatus],
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
                _append_unique_status(
                    open_access_status,
                    _provider_status(
                        UNPAYWALL_PROVIDER,
                        "open_access",
                        "failed",
                        retryable=True,
                        message=str(exc),
                    ),
                )
                enriched.append(paper)
                continue
            if isinstance(availability, ProviderWarning):
                warnings.append(availability)
                status: LiteratureProviderStatusValue = (
                    "disabled" if availability.status == "provider_disabled" else "failed"
                )
                _append_unique_status(
                    open_access_status,
                    _provider_status(
                        UNPAYWALL_PROVIDER,
                        "open_access",
                        status,
                        message=availability.message,
                    ),
                )
                enriched.append(paper)
                continue
            _append_unique_status(
                open_access_status,
                _provider_status(UNPAYWALL_PROVIDER, "open_access", "success", 1),
            )
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


def _provider_status(
    provider: str,
    operation: str,
    status: LiteratureProviderStatusValue,
    result_count: int = 0,
    *,
    retryable: bool = False,
    message: str | None = None,
) -> LiteratureProviderStatus:
    return LiteratureProviderStatus(
        provider=provider,
        operation=operation,
        status=status,
        result_count=result_count,
        retryable=retryable,
        message=message,
    )


def _append_unique_status(
    statuses: list[LiteratureProviderStatus],
    status: LiteratureProviderStatus,
) -> None:
    for existing in statuses:
        if (
            existing.provider == status.provider
            and existing.operation == status.operation
            and existing.status == status.status
        ):
            if status.status == "success":
                existing.result_count += status.result_count
            return
    statuses.append(status)


def _citation_candidates(
    papers: Sequence[LiteraturePaper],
    source_reason: str,
) -> list[LiteratureCandidateSummary]:
    candidates: list[LiteratureCandidateSummary] = []
    for paper in papers:
        rank_reasons = [source_reason]
        demotion_reasons: list[str] = []
        if paper.pmid:
            rank_reasons.append("has_pmid")
        else:
            demotion_reasons.append("doi_only_unresolved")
        candidates.append(
            candidate_summary(
                paper,
                rank_reasons=rank_reasons,
                demotion_reasons=demotion_reasons,
                source_tools=["citation_graph"],
            )
        )
    return candidates


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
