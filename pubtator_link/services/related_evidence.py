"""Related evidence candidate orchestration service."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pubtator_link.models.literature_graph import (
    LiteratureGraphResponseMeta,
    LiteraturePaper,
    ProviderWarning,
    PublicationCitationGraphRequest,
    RelatedEvidenceCandidate,
    RelatedEvidenceCandidatesRequest,
    RelatedEvidenceCandidatesResponse,
)
from pubtator_link.models.publication_metadata import PublicationMetadataRequest
from pubtator_link.services.literature_graph_compact import (
    coalesced_provider_warnings,
    json_size_class,
)
from pubtator_link.services.literature_paper_resolution import paper_from_publication_metadata


class RelatedEvidenceService:
    """Find related papers suitable for follow-up passage-level evidence review."""

    def __init__(
        self,
        *,
        discovery_service: Any,
        metadata_service: Any,
        citation_graph_service: Any,
    ) -> None:
        self.discovery_service = discovery_service
        self.metadata_service = metadata_service
        self.citation_graph_service = citation_graph_service

    async def find_candidates(
        self,
        request: RelatedEvidenceCandidatesRequest,
    ) -> RelatedEvidenceCandidatesResponse:
        """Return ranked, metadata-resolved related evidence candidates."""
        warnings: list[ProviderWarning] = []
        candidate_pmids: list[str] = []
        neighbor_scores: dict[str, int] = {}
        citation_pmids: set[str] = set()
        candidate_fetch_limit = _candidate_fetch_limit(request.max_results)

        try:
            related_scores = await self._find_related_article_scores(
                [request.pmid],
                candidate_fetch_limit,
            )
            for record in related_scores:
                pmid = str(record.pmid)
                if pmid == request.pmid:
                    continue
                neighbor_scores[pmid] = max(
                    neighbor_scores.get(pmid, 0),
                    int(record.neighbor_score),
                )
                candidate_pmids.append(pmid)
        except Exception as exc:
            warnings.append(_provider_failed_warning("ncbi_elink", exc))

        if request.include_citation_neighbors:
            try:
                graph = await self.citation_graph_service.get_citation_graph(
                    PublicationCitationGraphRequest(
                        pmid=request.pmid,
                        direction="both",
                        max_results=candidate_fetch_limit,
                    )
                )
                graph_candidate_pmids = [pmid for pmid in graph.candidate_pmids if pmid]
                citation_pmids.update(graph_candidate_pmids)
                candidate_pmids.extend(graph_candidate_pmids)
                warnings.extend(graph.meta.warnings)
            except Exception as exc:
                warnings.append(_provider_failed_warning("citation_graph", exc))

        deduped_pmids = [pmid for pmid in _dedupe(candidate_pmids) if pmid != request.pmid]
        source, source_warnings = await self._source_paper(request.pmid)
        warnings.extend(source_warnings)
        candidates, metadata_warnings = await self._metadata_candidates(
            request=request,
            pmids=deduped_pmids,
            neighbor_scores=neighbor_scores,
            citation_pmids=citation_pmids,
        )
        warnings.extend(metadata_warnings)
        candidates.sort(key=lambda candidate: _ranking_key(candidate, request))
        candidates = candidates[: request.max_results]
        ordered_pmids = [candidate.paper.pmid for candidate in candidates if candidate.paper.pmid]

        response = RelatedEvidenceCandidatesResponse(
            source=source,
            candidates=candidates,
            candidate_pmids=ordered_pmids,
            _meta=LiteratureGraphResponseMeta(
                response_mode=request.response_mode,
                warnings=coalesced_provider_warnings(warnings),
                next_commands=_next_commands(ordered_pmids),
            ),
        )
        response.meta.response_size_class = json_size_class(response.model_dump(by_alias=True))
        return response

    async def _source_paper(self, pmid: str) -> tuple[LiteraturePaper, list[ProviderWarning]]:
        try:
            metadata_response = await self.metadata_service.get_metadata(
                PublicationMetadataRequest(
                    pmids=[pmid],
                    include_mesh=False,
                    include_publication_types=True,
                    include_citations="none",
                    include_coverage=True,
                )
            )
        except Exception as exc:
            return LiteraturePaper(pmid=pmid), [_provider_failed_warning("pubmed_metadata", exc)]
        metadata = getattr(metadata_response, "metadata", [])
        if not metadata:
            return LiteraturePaper(pmid=pmid), []
        return _paper_from_metadata(metadata[0]), []

    async def _find_related_article_scores(self, pmids: list[str], limit: int) -> Any:
        finder = getattr(self.discovery_service, "find_related_article_scores", None)
        if finder is not None:
            return await finder(pmids, limit)
        client = self.discovery_service.client
        return await client.find_related_article_scores(pmids, limit)

    async def _metadata_candidates(
        self,
        *,
        request: RelatedEvidenceCandidatesRequest,
        pmids: list[str],
        neighbor_scores: dict[str, int],
        citation_pmids: set[str],
    ) -> tuple[list[RelatedEvidenceCandidate], list[ProviderWarning]]:
        if not pmids:
            return [], []

        warnings: list[ProviderWarning] = []
        try:
            metadata_response = await self.metadata_service.get_metadata(
                PublicationMetadataRequest(
                    pmids=pmids,
                    include_mesh=False,
                    include_publication_types=True,
                    include_citations="none",
                    include_coverage=True,
                )
            )
            metadata_by_pmid = {metadata.pmid: metadata for metadata in metadata_response.metadata}
            failed_pmids = getattr(metadata_response, "failed_pmids", {})
            if failed_pmids:
                warnings.append(
                    ProviderWarning(
                        provider="pubmed_metadata",
                        status="provider_failed",
                        retryable=True,
                        message=f"Metadata lookup failed for {len(failed_pmids)} PMID(s).",
                    )
                )
        except Exception as exc:
            metadata_by_pmid = {}
            warnings.append(_provider_failed_warning("pubmed_metadata", exc))

        candidates: list[RelatedEvidenceCandidate] = []
        for pmid in pmids:
            metadata = metadata_by_pmid.get(pmid)
            if metadata is None:
                paper = LiteraturePaper(pmid=pmid, status="unresolved_reference")
            else:
                paper = _paper_from_metadata(metadata)

            if not _matches_filters(paper, request):
                continue

            match_reasons = _match_reasons(
                pmid=pmid,
                paper=paper,
                request=request,
                neighbor_scores=neighbor_scores,
                citation_pmids=citation_pmids,
            )
            neighbor_score = neighbor_scores.get(pmid)
            candidates.append(
                RelatedEvidenceCandidate(
                    paper=paper,
                    score=float(neighbor_score or 0),
                    match_reasons=match_reasons,
                    pubmed_neighbor_score=neighbor_score,
                )
            )
        return candidates, warnings


def _paper_from_metadata(metadata: Any) -> LiteraturePaper:
    return paper_from_publication_metadata(metadata)


def _matches_filters(paper: LiteraturePaper, request: RelatedEvidenceCandidatesRequest) -> bool:
    if request.year_min is not None and (paper.year is None or paper.year < request.year_min):
        return False
    if request.year_max is not None and (paper.year is None or paper.year > request.year_max):
        return False
    return not (
        request.publication_types
        and not _publication_type_matches(paper.publication_types, request.publication_types)
    )


def _match_reasons(
    *,
    pmid: str,
    paper: LiteraturePaper,
    request: RelatedEvidenceCandidatesRequest,
    neighbor_scores: dict[str, int],
    citation_pmids: set[str],
) -> list[str]:
    reasons: list[str] = []
    if pmid in neighbor_scores:
        reasons.append("pubmed_neighbor_score")
    if pmid in citation_pmids:
        reasons.append("citation_neighbor")
    if _has_full_text(paper):
        reasons.append("full_text_available")
    if paper.availability.is_open_access:
        reasons.append("open_access_available")
    if request.publication_types and _publication_type_matches(
        paper.publication_types,
        request.publication_types,
    ):
        reasons.append("shared_publication_type")
        reasons.append("requested_publication_type")
    title_type_text = f"{paper.title or ''} {' '.join(paper.publication_types)}".casefold()
    if any(
        term in title_type_text for term in ("guideline", "recommendation", "consensus", "delphi")
    ):
        reasons.append("guideline_or_consensus_match")
    if any(term in title_type_text for term in ("child", "children", "pediatric", "paediatric")):
        reasons.append("pediatric_match")
    if any(term in title_type_text for term in ("turkey", "turkish", "mediterranean")):
        reasons.append("population_match")
    if any(term in title_type_text for term in ("variant", "genotype", "phenotype", "penetrance")):
        reasons.append("variant_or_genotype_match")
    if any(
        term in title_type_text for term in ("colchicine", "treatment", "resistance", "management")
    ):
        reasons.append("treatment_match")
    if request.year_min is not None or request.year_max is not None:
        reasons.append("year_window_match")
    return reasons


def _ranking_key(
    candidate: RelatedEvidenceCandidate,
    request: RelatedEvidenceCandidatesRequest,
) -> tuple[float, int, int, int, str]:
    paper = candidate.paper
    full_text_rank = int(request.prefer_full_text and _has_full_text(paper))
    type_rank = int(
        bool(request.publication_types)
        and _publication_type_matches(paper.publication_types, request.publication_types or [])
    )
    year_rank = paper.year or 0
    return (-candidate.score, -full_text_rank, -type_rank, -year_rank, paper.pmid or paper.key)


def _has_full_text(paper: LiteraturePaper) -> bool:
    return paper.status == "resolved_full_text_candidate" or paper.availability.has_pmc_full_text


def _publication_type_matches(
    publication_types: Iterable[str],
    requested_types: Iterable[str],
) -> bool:
    requested = {publication_type.casefold() for publication_type in requested_types}
    return any(publication_type.casefold() in requested for publication_type in publication_types)


def _provider_failed_warning(provider: str, exc: Exception) -> ProviderWarning:
    return ProviderWarning(
        provider=provider,
        status="provider_failed",
        retryable=True,
        message=f"{provider} lookup failed: {exc}",
    )


def _candidate_fetch_limit(max_results: int) -> int:
    return min(100, max(25, max_results * 5))


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def _next_commands(candidate_pmids: list[str]) -> list[dict[str, Any]]:
    if not candidate_pmids:
        return []
    return [
        {
            "tool": "pubtator.get_publication_passages",
            "arguments": {"pmids": candidate_pmids},
        }
    ]
