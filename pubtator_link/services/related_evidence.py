"""Related evidence candidate orchestration service."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pubtator_link.models.literature_graph import (
    LiteratureAvailability,
    LiteraturePaper,
    LiteratureResponseMeta,
    ProviderWarning,
    PublicationCitationGraphRequest,
    RelatedEvidenceCandidate,
    RelatedEvidenceCandidatesRequest,
    RelatedEvidenceCandidatesResponse,
)
from pubtator_link.models.publication_metadata import PublicationMetadataRequest


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

        if request.include_pubtator_search:
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

        return RelatedEvidenceCandidatesResponse(
            source=LiteraturePaper(pmid=request.pmid),
            candidates=candidates,
            candidate_pmids=ordered_pmids,
            _meta=LiteratureResponseMeta(
                warnings=warnings,
                next_commands=_next_commands(ordered_pmids),
            ),
        )

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
    has_full_text = metadata.coverage == "full_text" or bool(metadata.pmcid)
    return LiteraturePaper(
        pmid=metadata.pmid,
        doi=metadata.doi,
        pmcid=metadata.pmcid,
        title=metadata.title,
        journal=metadata.journal,
        year=metadata.pub_year,
        publication_types=metadata.publication_types,
        availability=LiteratureAvailability(has_pmc_full_text=has_full_text),
        status="resolved_full_text_candidate" if has_full_text else "resolved_metadata_only",
    )


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
    if request.publication_types and _publication_type_matches(
        paper.publication_types,
        request.publication_types,
    ):
        reasons.append("requested_publication_type")
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
