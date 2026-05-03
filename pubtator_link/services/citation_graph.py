"""Citation graph orchestration service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from pubtator_link.models.literature_graph import (
    CitationGraphDirection,
    LiteratureAvailability,
    LiteratureCandidateSummary,
    LiteratureGraphEdge,
    LiteratureGraphNode,
    LiteratureGraphProvenance,
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
from pubtator_link.services.literature_graph_compact import (
    candidate_summary,
    coalesced_provider_warnings,
    json_size_class,
)
from pubtator_link.services.literature_identifier_resolution import (
    DoiPmidResolver,
    DoiResolutionResult,
)
from pubtator_link.services.literature_paper_resolution import paper_from_publication_metadata
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
        reference_candidates = _citation_candidates(references, "source_reference")
        cited_by_candidates = _citation_candidates(cited_by, "source_cited_by")
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
        response = PublicationCitationGraphResponse(
            source=source,
            references=response_references,
            cited_by=response_cited_by,
            nodes=response_nodes,
            edges=response_edges,
            response_mode=request.response_mode,
            reference_candidates=response_reference_candidates,
            cited_by_candidates=response_cited_by_candidates,
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
            _meta=LiteratureGraphResponseMeta(
                response_mode=request.response_mode,
                warnings=coalesced_provider_warnings(warnings),
                next_commands=_next_commands(candidate_pmids),
                provider_status=[
                    *references_status,
                    *cited_by_status,
                    *identifier_resolution_status,
                    *open_access_status,
                ],
            ),
        )
        response.meta.response_size_class = json_size_class(response.model_dump(by_alias=True))
        return response

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
        return (
            [_paper_with_resolved_pmid(paper, result) for paper in references],
            [_paper_with_resolved_pmid(paper, result) for paper in cited_by],
            _doi_resolution_statuses(result),
        )

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
            if any(
                provenance.raw_status == "resolved_pmid_from_doi" for provenance in paper.provenance
            ):
                rank_reasons.append("resolved_pmid_from_doi")
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
