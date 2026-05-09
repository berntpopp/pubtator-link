"""Citation graph orchestration service."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Mapping, Sequence
from typing import Any, Literal, Protocol

from pubtator_link.models.literature_graph import (
    CitationGraphDirection,
    LiteratureAvailability,
    LiteratureCandidateSummary,
    LiteratureGraphEdge,
    LiteratureGraphNode,
    LiteratureGraphProvenance,
    LiteraturePaper,
    LiteratureProviderStatus,
    LiteratureProviderStatusValue,
    LiteratureQueryRelevance,
    ProviderWarning,
    PublicationCitationGraphRequest,
    PublicationCitationGraphResponse,
    dedupe_papers,
)
from pubtator_link.models.publication_metadata import PublicationMetadataRequest
from pubtator_link.services.literature_graph_compact import (
    candidate_summary,
    coalesced_provider_warnings,
    graph_budget_bytes,
    graph_detail_next_commands,
    graph_payload_json_bytes,
    graph_request_metadata,
    json_size_class,
    mark_graph_payload_truncated,
    normalize_query_text,
)
from pubtator_link.services.literature_identifier_resolution import (
    DoiPmidResolver,
    DoiResolutionResult,
)
from pubtator_link.services.literature_paper_resolution import (
    merge_literature_availability,
    paper_from_publication_metadata,
)
from pubtator_link.services.literature_providers import (
    CROSSREF_PROVIDER,
    EUROPE_PMC_PROVIDER,
    OPENALEX_PROVIDER,
    UNPAYWALL_PROVIDER,
)
from pubtator_link.services.publication_metadata import lookup_metadata_batched

OPEN_ACCESS_LOOKUP_CONCURRENCY = 3
CitationNeighborLane = Literal["references", "cited_by"]
ProviderLaneResult = tuple[
    CitationNeighborLane,
    list[LiteraturePaper],
    LiteratureProviderStatus,
    ProviderWarning | None,
]


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

    async def get_work_by_doi(self, doi: str) -> LiteraturePaper:
        """Fetch one OpenAlex work by DOI."""

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
        self.doi_resolver = DoiPmidResolver(
            discovery_service=discovery_service,
            openalex_service=openalex,
            pubmed_service=discovery_service,
        )

    async def get_citation_graph(
        self, request: PublicationCitationGraphRequest
    ) -> PublicationCitationGraphResponse:
        """Return citation neighbors for one PMID or DOI source."""
        warnings: list[ProviderWarning] = []
        source, source_resolution_result = await self._source_paper(request)
        references: list[LiteraturePaper] = []
        cited_by: list[LiteraturePaper] = []
        references_status: list[LiteratureProviderStatus] = []
        cited_by_status: list[LiteratureProviderStatus] = []
        identifier_resolution_status: list[LiteratureProviderStatus] = []
        open_access_status: list[LiteratureProviderStatus] = []
        if source_resolution_result is not None:
            identifier_resolution_status.extend(_doi_resolution_statuses(source_resolution_result))

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

        provider_lane_tasks: list[Awaitable[ProviderLaneResult]] = []

        if self.crossref:
            if request.direction not in {"references", "both"}:
                provider_lane_tasks.append(
                    _static_provider_lane_result(
                        "references",
                        _provider_status(CROSSREF_PROVIDER, "references", "not_requested"),
                    )
                )
            elif not source.doi:
                provider_lane_tasks.append(
                    _static_provider_lane_result(
                        "references",
                        _provider_status(
                            CROSSREF_PROVIDER,
                            "references",
                            "skipped",
                            message="DOI required",
                        ),
                    )
                )
            else:
                provider_lane_tasks.append(self._crossref_reference_lane(source.doi))

        if self.openalex:
            if request.direction not in {"references", "both"}:
                provider_lane_tasks.append(
                    _static_provider_lane_result(
                        "references",
                        _provider_status(OPENALEX_PROVIDER, "references", "not_requested"),
                    )
                )
            elif not source.doi:
                provider_lane_tasks.append(
                    _static_provider_lane_result(
                        "references",
                        _provider_status(
                            OPENALEX_PROVIDER,
                            "references",
                            "skipped",
                            message="DOI required",
                        ),
                    )
                )
            else:
                provider_lane_tasks.append(
                    self._openalex_reference_lane(source.doi, limit=request.max_results)
                )

        if self.europe_pmc:
            if request.direction not in {"cited_by", "both"}:
                provider_lane_tasks.append(
                    _static_provider_lane_result(
                        "cited_by",
                        _provider_status(EUROPE_PMC_PROVIDER, "cited_by", "not_requested"),
                    )
                )
            elif not source.pmid:
                provider_lane_tasks.append(
                    _static_provider_lane_result(
                        "cited_by",
                        _provider_status(
                            EUROPE_PMC_PROVIDER,
                            "cited_by",
                            "skipped",
                            message="PMID required",
                        ),
                    )
                )
            else:
                provider_lane_tasks.append(
                    self._europe_pmc_cited_by_lane(source.pmid, limit=request.max_results)
                )

        if self.openalex:
            if request.direction not in {"cited_by", "both"}:
                provider_lane_tasks.append(
                    _static_provider_lane_result(
                        "cited_by",
                        _provider_status(OPENALEX_PROVIDER, "cited_by", "not_requested"),
                    )
                )
            elif not source.doi:
                provider_lane_tasks.append(
                    _static_provider_lane_result(
                        "cited_by",
                        _provider_status(
                            OPENALEX_PROVIDER,
                            "cited_by",
                            "skipped",
                            message="DOI required",
                        ),
                    )
                )
            else:
                provider_lane_tasks.append(
                    self._openalex_cited_by_lane(source.doi, limit=request.max_results)
                )

        for lane, records, status, warning in await asyncio.gather(*provider_lane_tasks):
            if warning is not None:
                warnings.append(warning)
            if lane == "references":
                references.extend(records)
                references_status.append(status)
            else:
                cited_by.extend(records)
                cited_by_status.append(status)

        references = dedupe_papers(references)[: request.max_results]
        cited_by = dedupe_papers(cited_by)[: request.max_results]
        if request.resolve_reference_pmids and request.max_reference_resolution > 0:
            references, cited_by, neighbor_statuses = await self._resolve_neighbor_dois(
                references,
                cited_by,
                max_ids=request.max_reference_resolution,
            )
            identifier_resolution_status.extend(neighbor_statuses)
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
        all_neighbors = [*references, *cited_by]
        candidate_pmids = _candidate_pmids(all_neighbors)
        actionable_pmid_count = len(candidate_pmids)
        metadata_only_count = len(_metadata_only(all_neighbors))
        unresolved_doi_count = sum(1 for paper in all_neighbors if paper.doi and not paper.pmid)
        compact_status = (
            _compact_status_for_direction(request.direction)
            if request.response_mode == "compact"
            else {}
        )
        reference_candidates = _citation_candidates(
            references,
            "source_reference",
            query=request.query,
        )
        cited_by_candidates = _citation_candidates(
            cited_by,
            "source_cited_by",
            query=request.query,
        )
        reference_top_pmids = _top_candidate_pmids(reference_candidates)
        cited_by_top_pmids = _top_candidate_pmids(cited_by_candidates)
        reference_pmid_count = len(_candidate_pmids(references))
        cited_by_pmid_count = len(_candidate_pmids(cited_by))
        reference_sample_pmids = _candidate_pmids(references)[:3]
        cited_by_sample_pmids = _candidate_pmids(cited_by)[:3]
        compact_omitted_counts: dict[str, int] = {}
        response_references = references
        response_cited_by = cited_by
        response_reference_candidates = reference_candidates
        response_cited_by_candidates = cited_by_candidates
        response_metadata_only = _metadata_only(all_neighbors)
        response_nodes: list[LiteratureGraphNode] = []
        response_edges: list[LiteratureGraphEdge] = []
        if request.response_mode == "compact":
            response_references = []
            response_cited_by = []
            response_metadata_only = []
            response_reference_candidates, omitted_references = _compact_actionable_candidates(
                response_reference_candidates
            )
            response_cited_by_candidates, omitted_cited_by = _compact_actionable_candidates(
                response_cited_by_candidates
            )
            omitted_unresolved = omitted_references + omitted_cited_by
            if omitted_unresolved:
                compact_omitted_counts["doi_only_unresolved"] = omitted_unresolved
        elif request.response_mode == "nodes_edges":
            response_references = []
            response_cited_by = []
            response_reference_candidates = []
            response_cited_by_candidates = []
            response_metadata_only = []
            response_nodes, response_edges = _citation_nodes_edges(source, references, cited_by)
        if not request.include_provider_status:
            references_status = []
            cited_by_status = []
            identifier_resolution_status = []
            open_access_status = []
        provider_status = [
            *references_status,
            *cited_by_status,
            *identifier_resolution_status,
            *open_access_status,
        ]
        meta = graph_request_metadata(
            tool_name="pubtator.get_publication_citation_graph",
            request=request,
            source_versions=_citation_source_versions(request, self),
        ).model_copy(
            update={
                "truncated": bool(compact_omitted_counts),
                "omitted_counts": compact_omitted_counts,
                "warnings": coalesced_provider_warnings(warnings),
                "next_commands": [
                    *_next_commands(candidate_pmids),
                    *graph_detail_next_commands(
                        tool_name="pubtator.get_publication_citation_graph",
                        request=request,
                        modes=("full", "nodes_edges"),
                    ),
                ],
                "provider_status": provider_status,
            }
        )
        response = PublicationCitationGraphResponse(
            source=source,
            references=response_references,
            cited_by=response_cited_by,
            nodes=response_nodes,
            edges=response_edges,
            response_mode=request.response_mode,
            reference_candidates=response_reference_candidates,
            cited_by_candidates=response_cited_by_candidates,
            reference_top_pmids=reference_top_pmids,
            cited_by_top_pmids=cited_by_top_pmids,
            reference_pmid_count=reference_pmid_count,
            cited_by_pmid_count=cited_by_pmid_count,
            reference_sample_pmids=reference_sample_pmids,
            cited_by_sample_pmids=cited_by_sample_pmids,
            candidate_pmids=candidate_pmids,
            actionable_pmid_count=actionable_pmid_count,
            metadata_only_count=metadata_only_count,
            unresolved_doi_count=unresolved_doi_count,
            compact_status=compact_status,
            metadata_only=response_metadata_only,
            references_status=references_status,
            cited_by_status=cited_by_status,
            identifier_resolution_status=identifier_resolution_status,
            open_access_status=open_access_status,
            provider_status=provider_status,
            _meta=meta,
        )
        response = _enforce_citation_graph_budget(response)
        response.meta.response_size_class = json_size_class(response.model_dump(by_alias=True))
        return response

    async def _crossref_reference_lane(self, doi: str) -> ProviderLaneResult:
        assert self.crossref is not None
        started = time.monotonic()
        try:
            work = await self.crossref.get_work(doi)
            records = self.crossref.references_from_work(work)
            return (
                "references",
                records,
                _provider_status(
                    CROSSREF_PROVIDER,
                    "references",
                    "success" if records else "empty",
                    len(records),
                    elapsed_ms=_elapsed_ms(started),
                ),
                None,
            )
        except Exception as exc:  # pragma: no cover - exercised by provider fakes as needed
            return (
                "references",
                [],
                _provider_status(
                    CROSSREF_PROVIDER,
                    "references",
                    "failed",
                    retryable=True,
                    message=str(exc),
                    elapsed_ms=_elapsed_ms(started),
                ),
                _provider_failed_warning(CROSSREF_PROVIDER, exc),
            )

    async def _openalex_reference_lane(self, doi: str, *, limit: int) -> ProviderLaneResult:
        assert self.openalex is not None
        started = time.monotonic()
        try:
            records = await self.openalex.get_references(doi, limit=limit)
            return (
                "references",
                records,
                _provider_status(
                    OPENALEX_PROVIDER,
                    "references",
                    "success" if records else "empty",
                    len(records),
                    elapsed_ms=_elapsed_ms(started),
                ),
                None,
            )
        except Exception as exc:
            return (
                "references",
                [],
                _provider_status(
                    OPENALEX_PROVIDER,
                    "references",
                    "failed",
                    retryable=True,
                    message=str(exc),
                    elapsed_ms=_elapsed_ms(started),
                ),
                _provider_failed_warning(OPENALEX_PROVIDER, exc),
            )

    async def _europe_pmc_cited_by_lane(self, pmid: str, *, limit: int) -> ProviderLaneResult:
        assert self.europe_pmc is not None
        started = time.monotonic()
        try:
            records = await self.europe_pmc.get_citations(pmid, limit=limit)
            return (
                "cited_by",
                records,
                _provider_status(
                    EUROPE_PMC_PROVIDER,
                    "cited_by",
                    "success" if records else "empty",
                    len(records),
                    elapsed_ms=_elapsed_ms(started),
                ),
                None,
            )
        except Exception as exc:
            return (
                "cited_by",
                [],
                _provider_status(
                    EUROPE_PMC_PROVIDER,
                    "cited_by",
                    "failed",
                    retryable=True,
                    message=str(exc),
                    elapsed_ms=_elapsed_ms(started),
                ),
                _provider_failed_warning(EUROPE_PMC_PROVIDER, exc),
            )

    async def _openalex_cited_by_lane(self, doi: str, *, limit: int) -> ProviderLaneResult:
        assert self.openalex is not None
        started = time.monotonic()
        try:
            records = await self.openalex.get_cited_by(doi, limit=limit)
            return (
                "cited_by",
                records,
                _provider_status(
                    OPENALEX_PROVIDER,
                    "cited_by",
                    "success" if records else "empty",
                    len(records),
                    elapsed_ms=_elapsed_ms(started),
                ),
                None,
            )
        except Exception as exc:
            return (
                "cited_by",
                [],
                _provider_status(
                    OPENALEX_PROVIDER,
                    "cited_by",
                    "failed",
                    retryable=True,
                    message=str(exc),
                    elapsed_ms=_elapsed_ms(started),
                ),
                _provider_failed_warning(OPENALEX_PROVIDER, exc),
            )

    async def _source_paper(
        self,
        request: PublicationCitationGraphRequest,
    ) -> tuple[LiteraturePaper, DoiResolutionResult | None]:
        if request.pmid:
            if request.resolve_metadata:
                metadata = await self._metadata_for_pmid(request.pmid)
                if metadata is not None:
                    return paper_from_publication_metadata(metadata), None
            return LiteraturePaper(pmid=request.pmid), None
        if request.doi:
            resolution_result = await self.doi_resolver.resolve([request.doi], max_ids=1)
            pmid = next(iter(resolution_result.resolved.values()), None)
            if pmid is not None:
                if request.resolve_metadata:
                    metadata = await self._metadata_for_pmid(pmid)
                    if metadata is not None:
                        paper = paper_from_publication_metadata(metadata)
                        if paper.doi:
                            return paper, resolution_result
                        return paper.model_copy(update={"doi": request.doi}), resolution_result
                return LiteraturePaper(pmid=pmid, doi=request.doi), resolution_result
            return LiteraturePaper(doi=request.doi), resolution_result
        raise ValueError("exactly one of pmid or doi is required")

    async def _pmid_for_doi(self, doi: str) -> str | None:
        result = await self.doi_resolver.resolve([doi], max_ids=1)
        return next(iter(result.resolved.values()), None)

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

    async def _resolve_neighbor_dois(
        self,
        references: list[LiteraturePaper],
        cited_by: list[LiteraturePaper],
        *,
        max_ids: int,
    ) -> tuple[list[LiteraturePaper], list[LiteraturePaper], list[LiteratureProviderStatus]]:
        doi_only_papers = [
            paper for paper in [*references, *cited_by] if paper.doi and not paper.pmid
        ]
        if not doi_only_papers:
            return references, cited_by, []

        result = await self.doi_resolver.resolve(
            [paper.doi for paper in doi_only_papers if paper.doi],
            max_ids=max_ids,
        )
        resolved_references = [_paper_with_resolved_pmid(paper, result) for paper in references]
        resolved_cited_by = [_paper_with_resolved_pmid(paper, result) for paper in cited_by]
        resolved_references, resolved_cited_by = await self._with_resolved_neighbor_metadata(
            resolved_references,
            resolved_cited_by,
        )
        return (resolved_references, resolved_cited_by, _doi_resolution_statuses(result))

    async def _with_resolved_neighbor_metadata(
        self,
        references: list[LiteraturePaper],
        cited_by: list[LiteraturePaper],
    ) -> tuple[list[LiteraturePaper], list[LiteraturePaper]]:
        if self.metadata_service is None:
            return references, cited_by
        pmids = _candidate_pmids([*references, *cited_by])
        if not pmids:
            return references, cited_by
        try:
            response = await lookup_metadata_batched(
                self.metadata_service,
                pmids,
                include_mesh=False,
                include_publication_types=True,
                include_citations="none",
                include_coverage=True,
            )
        except Exception:
            return references, cited_by
        metadata_by_pmid = {
            metadata.pmid: paper_from_publication_metadata(metadata)
            for metadata in getattr(response, "metadata", [])
            if getattr(metadata, "pmid", None)
        }

        def enrich(paper: LiteraturePaper) -> LiteraturePaper:
            if not paper.pmid or paper.pmid not in metadata_by_pmid:
                return paper
            return merge_literature_availability(metadata_by_pmid[paper.pmid], paper)

        return [enrich(paper) for paper in references], [enrich(paper) for paper in cited_by]

    async def _with_open_access_status(
        self,
        papers: list[LiteraturePaper],
        warnings: list[ProviderWarning],
        open_access_status: list[LiteratureProviderStatus],
    ) -> list[LiteraturePaper]:
        if self.unpaywall is None:
            return papers
        unpaywall = self.unpaywall
        semaphore = asyncio.Semaphore(OPEN_ACCESS_LOOKUP_CONCURRENCY)

        async def enrich_one(
            paper: LiteraturePaper,
        ) -> tuple[LiteraturePaper, LiteratureProviderStatus | None, ProviderWarning | None]:
            if not paper.doi:
                return paper, None, None
            async with semaphore:
                started = time.monotonic()
                try:
                    availability = await unpaywall.get_oa_status(paper.doi)
                except Exception as exc:
                    return (
                        paper,
                        _provider_status(
                            UNPAYWALL_PROVIDER,
                            "open_access",
                            "failed",
                            retryable=True,
                            message=str(exc),
                            elapsed_ms=_elapsed_ms(started),
                        ),
                        _provider_failed_warning(UNPAYWALL_PROVIDER, exc),
                    )
            if isinstance(availability, ProviderWarning):
                status: LiteratureProviderStatusValue
                warning: ProviderWarning | None = None
                if availability.status == "provider_no_match":
                    status = "empty"
                else:
                    warning = availability
                    status = "disabled" if availability.status == "provider_disabled" else "failed"
                return (
                    paper,
                    _provider_status(
                        UNPAYWALL_PROVIDER,
                        "open_access",
                        status,
                        message=availability.message,
                        elapsed_ms=_elapsed_ms(started),
                    ),
                    warning,
                )
            return (
                _paper_with_availability(paper, availability),
                _provider_status(
                    UNPAYWALL_PROVIDER,
                    "open_access",
                    "success",
                    1,
                    elapsed_ms=_elapsed_ms(started),
                ),
                None,
            )

        enriched: list[LiteraturePaper] = []
        for paper, status, warning in await asyncio.gather(
            *(enrich_one(paper) for paper in papers)
        ):
            enriched.append(paper)
            if warning is not None:
                warnings.append(warning)
            if status is not None:
                _append_unique_status(open_access_status, status)
        return enriched


def _provider_failed_warning(provider: str, exc: Exception) -> ProviderWarning:
    return ProviderWarning(
        provider=provider,
        status="provider_failed",
        retryable=True,
        message=f"{provider} citation lookup failed: {exc}",
    )


async def _static_provider_lane_result(
    lane: CitationNeighborLane,
    status: LiteratureProviderStatus,
) -> ProviderLaneResult:
    return lane, [], status, None


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


def _paper_with_resolved_pmid(
    paper: LiteraturePaper,
    result: DoiResolutionResult,
) -> LiteraturePaper:
    if not paper.doi or paper.pmid:
        return paper
    pmid = result.resolved.get(paper.doi)
    if pmid is None:
        return paper
    return paper.model_copy(
        update={
            "pmid": pmid,
            "provenance": [
                *paper.provenance,
                LiteratureGraphProvenance(
                    provider=result.resolution_sources.get(paper.doi, "ncbi_idconv"),
                    source_id=paper.doi,
                    raw_status="resolved_pmid_from_doi",
                ),
            ],
        }
    )


def _doi_resolution_statuses(result: DoiResolutionResult) -> list[LiteratureProviderStatus]:
    statuses: list[LiteratureProviderStatus] = []
    for provider in ("ncbi_idconv", OPENALEX_PROVIDER, "pubmed_esearch"):
        result_count = result.provider_result_counts.get(provider, 0)
        no_match_count = result.provider_no_match_counts.get(provider, 0)
        failed_count = result.provider_failed_counts.get(provider, 0)
        timeout_count = result.provider_timeout_counts.get(provider, 0)
        if result_count == 0 and no_match_count == 0 and failed_count == 0 and timeout_count == 0:
            continue
        if failed_count or timeout_count:
            status: LiteratureProviderStatusValue = (
                "partial" if result_count or no_match_count else "failed"
            )
        elif result_count and no_match_count:
            status = "partial"
        elif result_count:
            status = "success"
        else:
            status = "empty"
        statuses.append(
            LiteratureProviderStatus(
                provider=provider,
                operation="doi_to_pmid",
                status=status,
                result_count=result_count,
                retryable=bool(failed_count or timeout_count),
                message=(
                    f"resolved={result_count} no_match={no_match_count} "
                    f"cached={result.cached_count} skipped={result.skipped_count} "
                    f"failed={failed_count} timeout={timeout_count}"
                ),
            )
        )
    if not statuses and (result.skipped_count or result.failed_count or result.timeout_count):
        status = "skipped" if result.skipped_count and not result.failed_count else "failed"
        statuses.append(
            LiteratureProviderStatus(
                provider="ncbi_idconv",
                operation="doi_to_pmid",
                status=status,
                retryable=bool(result.failed_count or result.timeout_count),
                message=(
                    f"resolved={result.resolved_count} unresolved={result.unresolved_count} "
                    f"cached={result.cached_count} skipped={result.skipped_count} "
                    f"failed={result.failed_count} timeout={result.timeout_count}"
                ),
            )
        )
    return statuses


def _provider_status(
    provider: str,
    operation: str,
    status: LiteratureProviderStatusValue,
    result_count: int = 0,
    *,
    retryable: bool = False,
    message: str | None = None,
    elapsed_ms: int | None = None,
    budget_ms: int | None = None,
) -> LiteratureProviderStatus:
    return LiteratureProviderStatus(
        provider=provider,
        operation=operation,
        status=status,
        result_count=result_count,
        retryable=retryable,
        message=message,
        elapsed_ms=elapsed_ms,
        budget_ms=budget_ms,
    )


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))


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
    *,
    query: str | None,
) -> list[LiteratureCandidateSummary]:
    candidates: list[LiteratureCandidateSummary] = []
    for paper in papers:
        rank_reasons = [source_reason]
        demotion_reasons: list[str] = []
        if paper.pmid:
            rank_reasons.append("has_pmid")
            if any(
                provenance.raw_status == "resolved_pmid_from_doi" for provenance in paper.provenance
            ):
                rank_reasons.append("resolved_pmid_from_doi")
        else:
            demotion_reasons.append("doi_only_unresolved")
        score, relevance, scoring_reasons = _citation_query_score(
            paper,
            query=query,
            source_reason=source_reason,
        )
        rank_reasons.extend(scoring_reasons)
        candidates.append(
            candidate_summary(
                paper,
                score=score,
                relevance_to_query=relevance,
                rank_reasons=rank_reasons,
                demotion_reasons=demotion_reasons,
                source_tools=["citation_graph"],
            )
        )
    return sorted(
        candidates,
        key=lambda candidate: (
            -float(candidate.score or 0),
            -(candidate.year or 0),
            candidate.pmid or candidate.doi or candidate.title or "",
        ),
    )


def _citation_query_score(
    paper: LiteraturePaper,
    *,
    query: str | None,
    source_reason: str,
) -> tuple[float | None, LiteratureQueryRelevance | None, list[str]]:
    if not query:
        return None, None, []
    query_terms = _query_terms(query)
    searchable = normalize_query_text(
        " ".join(
            value
            for value in [
                paper.title or "",
                paper.journal or "",
                " ".join(paper.publication_types),
            ]
            if value
        )
    )
    matched_terms = [term for term in query_terms if term in searchable]
    score = 0.0
    reasons: list[str] = []
    if matched_terms:
        score += min(len(matched_terms), 6) * 0.14
        reasons.append("query_term_overlap")
    if paper.availability.has_pmc_full_text or paper.availability.is_open_access:
        score += 0.08
        reasons.append("accessible_candidate")
    if paper.year:
        score += max(0.0, min(0.12, (paper.year - 2015) * 0.012))
        reasons.append("recency")
    title = normalize_query_text(paper.title)
    if any(term in title for term in ("guideline", "recommendation", "consensus", "eular")):
        score += 0.18
        reasons.append("guideline_signal")
    if source_reason == "source_cited_by":
        score += 0.05
        reasons.append("cited_by_signal")
    score = max(0.0, min(1.0, score))
    return (
        score,
        LiteratureQueryRelevance(
            score=score,
            matched_terms=matched_terms[:8],
            reasons=reasons[:8],
        ),
        reasons,
    )


def _query_terms(query: str | None) -> list[str]:
    normalized = normalize_query_text(query)
    terms = normalized.replace("/", " ").replace("-", " ").split()
    stop_words = {"and", "or", "the", "for", "with", "of", "in", "a", "an", "to"}
    return list(dict.fromkeys(term for term in terms if len(term) > 1 and term not in stop_words))


def _top_candidate_pmids(candidates: Sequence[LiteratureCandidateSummary]) -> list[str]:
    return [candidate.pmid for candidate in candidates if candidate.pmid][:20]


def _compact_actionable_candidates(
    candidates: list[LiteratureCandidateSummary],
) -> tuple[list[LiteratureCandidateSummary], int]:
    actionable = [candidate for candidate in candidates if candidate.pmid]
    return actionable, len(candidates) - len(actionable)


def _compact_status_for_direction(direction: CitationGraphDirection) -> dict[str, str]:
    return {
        "references": (
            "candidates_only" if direction in {"references", "both"} else "not_requested"
        ),
        "cited_by": ("candidates_only" if direction in {"cited_by", "both"} else "not_requested"),
    }


def _citation_nodes_edges(
    source: LiteraturePaper,
    references: Sequence[LiteraturePaper],
    cited_by: Sequence[LiteraturePaper],
) -> tuple[list[LiteratureGraphNode], list[LiteratureGraphEdge]]:
    papers = dedupe_papers([source, *references, *cited_by])
    nodes = [LiteratureGraphNode(node_type="paper", paper=paper) for paper in papers]
    edges = [
        LiteratureGraphEdge(
            source=source.key,
            target=paper.key,
            edge_type="cites",
            reasons=["source_reference"],
            provenance=[LiteratureGraphProvenance(provider="citation_graph")],
        )
        for paper in references
    ]
    edges.extend(
        LiteratureGraphEdge(
            source=source.key,
            target=paper.key,
            edge_type="cited_by",
            reasons=["source_cited_by"],
            provenance=[LiteratureGraphProvenance(provider="citation_graph")],
        )
        for paper in cited_by
    )
    return nodes, edges


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
            "arguments": {"pmids": candidate_pmids},
        },
    ]


def _citation_source_versions(
    request: PublicationCitationGraphRequest,
    service: CitationGraphService,
) -> dict[str, str]:
    versions: dict[str, str] = {"pubmed": "live"}
    if service.crossref is not None:
        versions[CROSSREF_PROVIDER] = "live"
    if service.europe_pmc is not None:
        versions[EUROPE_PMC_PROVIDER] = "live"
    if service.openalex is not None:
        versions[OPENALEX_PROVIDER] = "live"
    if request.include_open_access_status and service.unpaywall is not None:
        versions[UNPAYWALL_PROVIDER] = "live"
    return versions


def _enforce_citation_graph_budget(
    response: PublicationCitationGraphResponse,
) -> PublicationCitationGraphResponse:
    budget = graph_budget_bytes(response.response_mode)
    if budget is None:
        return response
    if graph_payload_json_bytes(response) <= budget:
        if response.meta.truncated and response.meta.budget_advice is None:
            return response.model_copy(
                update={
                    "meta": mark_graph_payload_truncated(
                        response.meta,
                        omitted_counts={},
                        budget_bytes=budget,
                    )
                }
            )
        return response

    omitted: dict[str, int] = {}
    reference_candidates = [
        _budget_compact_candidate(candidate) for candidate in response.reference_candidates
    ]
    cited_by_candidates = [
        _budget_compact_candidate(candidate) for candidate in response.cited_by_candidates
    ]
    compacted = response.model_copy(
        update={
            "reference_candidates": reference_candidates,
            "cited_by_candidates": cited_by_candidates,
        }
    )
    if graph_payload_json_bytes(compacted) <= budget:
        omitted["candidate_details"] = len(response.reference_candidates) + len(
            response.cited_by_candidates
        )
        return compacted.model_copy(
            update={
                "meta": mark_graph_payload_truncated(
                    compacted.meta,
                    omitted_counts=omitted,
                    budget_bytes=budget,
                )
            }
        )

    compacted, omitted = _drop_citation_candidates_to_budget(
        compacted,
        budget=budget,
        omitted_counts=omitted,
    )
    return compacted.model_copy(
        update={
            "meta": mark_graph_payload_truncated(
                compacted.meta,
                omitted_counts=omitted,
                budget_bytes=budget,
            )
        }
    )


def _drop_citation_candidates_to_budget(
    response: PublicationCitationGraphResponse,
    *,
    budget: int,
    omitted_counts: dict[str, int],
) -> tuple[PublicationCitationGraphResponse, dict[str, int]]:
    overage = graph_payload_json_bytes(response) - budget
    if overage <= 0:
        return response, omitted_counts

    cited_by_candidates, dropped_cited_by, overage = _drop_suffix_by_estimated_bytes(
        response.cited_by_candidates,
        overage,
        min_keep=3 if response.cited_by_top_pmids else 0,
    )
    reference_candidates, dropped_references, overage = _drop_suffix_by_estimated_bytes(
        response.reference_candidates,
        overage,
        min_keep=3 if response.reference_top_pmids else 0,
    )
    if dropped_cited_by:
        omitted_counts["cited_by_candidates"] = (
            omitted_counts.get("cited_by_candidates", 0) + dropped_cited_by
        )
    if dropped_references:
        omitted_counts["reference_candidates"] = (
            omitted_counts.get("reference_candidates", 0) + dropped_references
        )

    trimmed = response.model_copy(
        update={
            "reference_candidates": reference_candidates,
            "cited_by_candidates": cited_by_candidates,
        }
    )
    if graph_payload_json_bytes(trimmed) <= budget:
        return trimmed, omitted_counts

    keep_cited_by = trimmed.cited_by_candidates[:3] if response.cited_by_top_pmids else []
    keep_references = trimmed.reference_candidates[:3] if response.reference_top_pmids else []
    omitted_counts["reference_candidates"] = omitted_counts.get("reference_candidates", 0) + max(
        0,
        len(trimmed.reference_candidates) - len(keep_references),
    )
    omitted_counts["cited_by_candidates"] = omitted_counts.get("cited_by_candidates", 0) + max(
        0,
        len(trimmed.cited_by_candidates) - len(keep_cited_by),
    )
    return trimmed.model_copy(
        update={
            "reference_candidates": keep_references,
            "cited_by_candidates": keep_cited_by,
        }
    ), omitted_counts


def _drop_suffix_by_estimated_bytes(
    candidates: list[LiteratureCandidateSummary],
    overage: int,
    *,
    min_keep: int = 0,
) -> tuple[list[LiteratureCandidateSummary], int, int]:
    reclaimed = 0
    dropped = 0
    droppable = candidates[min_keep:]
    for candidate in reversed(droppable):
        reclaimed += graph_payload_json_bytes(candidate)
        dropped += 1
        if reclaimed >= overage:
            break
    if dropped == 0:
        return candidates, 0, overage
    return candidates[: len(candidates) - dropped], dropped, max(0, overage - reclaimed)


def _budget_compact_candidate(
    candidate: LiteratureCandidateSummary,
) -> LiteratureCandidateSummary:
    return candidate.model_copy(
        update={
            "publication_types": candidate.publication_types[:3],
            "access_flags": {},
            "rank_reasons": candidate.rank_reasons[:3],
            "demotion_reasons": candidate.demotion_reasons[:3],
            "signals": candidate.signals[:5],
            "source_tools": [],
            "next_actions": [],
        }
    )
