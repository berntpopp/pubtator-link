"""Related evidence candidate orchestration service."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from typing import Any

from pubtator_link.models.literature_graph import (
    LiteraturePaper,
    LiteratureProviderStatus,
    LiteratureProviderStatusValue,
    ProviderWarning,
    PublicationCitationGraphRequest,
    RelatedEvidenceCandidate,
    RelatedEvidenceCandidatesRequest,
    RelatedEvidenceCandidatesResponse,
)
from pubtator_link.models.publication_metadata import PublicationMetadataRequest
from pubtator_link.services.literature_graph_compact import (
    candidate_summary,
    coalesced_provider_warnings,
    graph_detail_next_commands,
    graph_request_metadata,
    json_size_class,
)
from pubtator_link.services.literature_paper_resolution import (
    deduped_signals,
    paper_from_publication_metadata,
)
from pubtator_link.services.publication_metadata import lookup_metadata_batched


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
        provider_status: list[LiteratureProviderStatus] = []
        candidate_pmids: list[str] = []
        neighbor_scores: dict[str, int] = {}
        citation_pmids: set[str] = set()
        candidate_fetch_limit = _candidate_fetch_limit(request.max_results)

        elink_started = time.monotonic()
        elink_task = asyncio.create_task(
            self._find_related_article_scores([request.pmid], candidate_fetch_limit)
        )
        source_started = time.monotonic()
        source_task = asyncio.create_task(self._source_paper(request.pmid))
        graph_started = time.monotonic()
        graph_task = (
            asyncio.create_task(
                self.citation_graph_service.get_citation_graph(
                    PublicationCitationGraphRequest(
                        pmid=request.pmid,
                        direction="both",
                        max_results=candidate_fetch_limit,
                    )
                )
            )
            if request.include_citation_neighbors
            else None
        )

        try:
            related_scores = await elink_task
        except Exception as exc:
            warnings.append(_provider_failed_warning("ncbi_elink", exc))
            provider_status.append(
                _provider_status(
                    "ncbi_elink",
                    "related_articles",
                    "failed",
                    retryable=True,
                    message=str(exc),
                    elapsed_ms=_elapsed_ms(elink_started),
                )
            )
        else:
            for record in related_scores:
                pmid = str(record.pmid)
                if pmid == request.pmid:
                    continue
                neighbor_scores[pmid] = max(
                    neighbor_scores.get(pmid, 0),
                    int(record.neighbor_score),
                )
                candidate_pmids.append(pmid)
            provider_status.append(
                _provider_status(
                    "ncbi_elink",
                    "related_articles",
                    "success" if related_scores else "empty",
                    len(related_scores),
                    elapsed_ms=_elapsed_ms(elink_started),
                )
            )
        try:
            source, source_warnings = await source_task
        except Exception as exc:
            source = LiteraturePaper(pmid=request.pmid)
            warnings.append(_provider_failed_warning("pubmed_metadata", exc))
            provider_status.append(
                _provider_status(
                    "pubmed_metadata",
                    "source_metadata",
                    "failed",
                    retryable=True,
                    message=str(exc),
                    elapsed_ms=_elapsed_ms(source_started),
                )
            )
        else:
            warnings.extend(source_warnings)
            provider_status.append(
                _provider_status(
                    "pubmed_metadata",
                    "source_metadata",
                    "success" if source.title else "empty",
                    int(bool(source.title)),
                    retryable=bool(source_warnings),
                    elapsed_ms=_elapsed_ms(source_started),
                )
            )
        if graph_task is not None:
            try:
                graph = await asyncio.wait_for(
                    graph_task,
                    timeout=request.citation_graph_timeout_ms / 1000,
                )
            except TimeoutError as exc:
                graph_task.cancel()
                warnings.append(_provider_failed_warning("citation_graph", exc))
                provider_status.append(
                    _provider_status(
                        "citation_graph",
                        "candidate_neighbors",
                        "failed",
                        retryable=True,
                        message="citation_graph timed out; retry with include_citation_neighbors=false.",
                        elapsed_ms=_elapsed_ms(graph_started),
                        budget_ms=request.citation_graph_timeout_ms,
                    )
                )
            except Exception as exc:
                warnings.append(_provider_failed_warning("citation_graph", exc))
                provider_status.append(
                    _provider_status(
                        "citation_graph",
                        "candidate_neighbors",
                        "failed",
                        retryable=True,
                        message=str(exc),
                        elapsed_ms=_elapsed_ms(graph_started),
                        budget_ms=request.citation_graph_timeout_ms,
                    )
                )
            else:
                graph_candidate_pmids = [pmid for pmid in graph.candidate_pmids if pmid]
                citation_pmids.update(graph_candidate_pmids)
                candidate_pmids.extend(graph_candidate_pmids)
                warnings.extend(graph.meta.warnings)
                provider_status.append(
                    _provider_status(
                        "citation_graph",
                        "candidate_neighbors",
                        "success" if graph_candidate_pmids else "empty",
                        len(graph_candidate_pmids),
                        retryable=bool(graph.meta.warnings),
                        elapsed_ms=_elapsed_ms(graph_started),
                        budget_ms=request.citation_graph_timeout_ms,
                    )
                )
        deduped_pmids = [pmid for pmid in _dedupe(candidate_pmids) if pmid != request.pmid]
        candidates, metadata_warnings, metadata_status = await self._metadata_candidates(
            request=request,
            pmids=deduped_pmids,
            neighbor_scores=neighbor_scores,
            citation_pmids=citation_pmids,
        )
        warnings.extend(metadata_warnings)
        provider_status.append(metadata_status)
        candidates.sort(key=lambda candidate: _ranking_key(candidate, request))
        candidate_count_before_limit = len(candidates)
        omitted_candidate_preview = [
            candidate_summary(
                candidate.paper,
                score=candidate.score,
                rank_reasons=candidate.match_reasons,
                source_tools=["related_evidence"],
            )
            for candidate in candidates[request.max_results : request.max_results + 5]
        ]
        candidates = candidates[: request.max_results]
        omitted_counts = {
            "candidates": max(0, candidate_count_before_limit - len(candidates)),
        }
        _attach_normalized_scores(candidates)
        ordered_pmids = [candidate.paper.pmid for candidate in candidates if candidate.paper.pmid]
        meta = graph_request_metadata(
            tool_name="pubtator.find_related_evidence_candidates",
            request=request,
            source_versions={
                "pubmed": "live",
                "ncbi_elink": "live",
                "citation_graph": "live",
            },
        ).model_copy(
            update={
                "warnings": coalesced_provider_warnings(warnings),
                "next_commands": [
                    *graph_detail_next_commands(
                        tool_name="pubtator.find_related_evidence_candidates",
                        request=request,
                        modes=("full",),
                    ),
                    *_recovery_commands(request, provider_status),
                    *_next_commands(ordered_pmids),
                ],
                "truncated": any(count > 0 for count in omitted_counts.values()),
                "omitted_counts": {
                    key: value for key, value in omitted_counts.items() if value > 0
                },
                "provider_status": provider_status,
            }
        )

        response = RelatedEvidenceCandidatesResponse(
            source=source,
            candidates=candidates,
            candidate_pmids=ordered_pmids,
            omitted_candidate_preview=omitted_candidate_preview,
            provider_status=provider_status,
            _meta=meta,
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
    ) -> tuple[
        list[RelatedEvidenceCandidate],
        list[ProviderWarning],
        LiteratureProviderStatus,
    ]:
        started = time.monotonic()
        if not pmids:
            return (
                [],
                [],
                _provider_status(
                    "pubmed_metadata",
                    "candidate_metadata",
                    "empty",
                    elapsed_ms=_elapsed_ms(started),
                ),
            )

        warnings: list[ProviderWarning] = []
        try:
            metadata_response = await asyncio.wait_for(
                lookup_metadata_batched(
                    self.metadata_service,
                    pmids,
                    include_mesh=False,
                    include_publication_types=True,
                    include_citations="none",
                    include_coverage=True,
                ),
                timeout=request.metadata_timeout_ms / 1000,
            )
        except TimeoutError as exc:
            warnings.append(_provider_failed_warning("pubmed_metadata", exc))
            return (
                [
                    RelatedEvidenceCandidate(
                        paper=LiteraturePaper(pmid=pmid, status="unresolved_reference"),
                        score=float(neighbor_scores.get(pmid) or 0),
                        match_reasons=_match_reasons(
                            pmid=pmid,
                            paper=LiteraturePaper(pmid=pmid, status="unresolved_reference"),
                            request=request,
                            neighbor_scores=neighbor_scores,
                            citation_pmids=citation_pmids,
                        ),
                        pubmed_neighbor_score=neighbor_scores.get(pmid),
                    )
                    for pmid in pmids
                ],
                warnings,
                _provider_status(
                    "pubmed_metadata",
                    "candidate_metadata",
                    "failed",
                    retryable=True,
                    message="pubmed_metadata timed out; retry with fewer max_results or metadata_timeout_ms.",
                    elapsed_ms=_elapsed_ms(started),
                    budget_ms=request.metadata_timeout_ms,
                ),
            )
        except Exception as exc:
            warnings.append(_provider_failed_warning("pubmed_metadata", exc))
            return (
                [],
                warnings,
                _provider_status(
                    "pubmed_metadata",
                    "candidate_metadata",
                    "failed",
                    retryable=True,
                    message=str(exc),
                    elapsed_ms=_elapsed_ms(started),
                    budget_ms=request.metadata_timeout_ms,
                ),
            )
        metadata_by_pmid = {metadata.pmid: metadata for metadata in metadata_response.metadata}
        failed_pmids = getattr(metadata_response, "failed_pmids", {})
        for warning in metadata_response.meta.get("warnings", []):
            warnings.append(
                ProviderWarning(
                    provider="pubmed_metadata",
                    status="provider_failed",
                    retryable=True,
                    message=f"PubMed metadata warning: {warning}",
                    code=_metadata_warning_code(warning),
                    next_steps=_metadata_warning_next_steps(warning),
                )
            )

        if failed_pmids:
            warnings.append(
                ProviderWarning(
                    provider="pubmed_metadata",
                    status="provider_failed",
                    retryable=True,
                    message=f"Metadata lookup failed for {len(failed_pmids)} PMID(s).",
                )
            )

        if metadata_response.metadata and failed_pmids:
            metadata_status: LiteratureProviderStatusValue = "partial"
        elif metadata_response.metadata:
            metadata_status = "success"
        elif failed_pmids:
            metadata_status = "failed"
        else:
            metadata_status = "empty"
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
        return (
            candidates,
            warnings,
            _provider_status(
                "pubmed_metadata",
                "candidate_metadata",
                metadata_status,
                len(metadata_response.metadata),
                retryable=bool(failed_pmids),
                message=f"failed_pmids={len(failed_pmids)}" if failed_pmids else None,
                elapsed_ms=_elapsed_ms(started),
                budget_ms=request.metadata_timeout_ms,
            ),
        )


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


def _attach_normalized_scores(candidates: list[RelatedEvidenceCandidate]) -> None:
    raw_scores = [
        candidate.pubmed_neighbor_score
        for candidate in candidates
        if candidate.pubmed_neighbor_score is not None
    ]
    if not raw_scores:
        for candidate in candidates:
            candidate.signals = deduped_signals(candidate.match_reasons)
        return
    low = min(raw_scores)
    high = max(raw_scores)
    span = high - low
    for candidate in candidates:
        raw = candidate.pubmed_neighbor_score
        normalized = (
            1.0
            if span == 0 and raw is not None
            else ((raw - low) / span if raw is not None else None)
        )
        candidate.normalized_neighbor_score = normalized
        candidate.signals = deduped_signals(candidate.match_reasons)


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


def _metadata_warning_code(warning: object) -> str | None:
    if isinstance(warning, str) and warning:
        return warning
    return None


def _metadata_warning_next_steps(warning: object) -> list[str]:
    if warning == "coverage_lookup_failed":
        return [
            "Retry with include_citation_neighbors=false or continue with metadata-only ranking; "
            "coverage can be rechecked during index_review_evidence."
        ]
    if isinstance(warning, str) and warning:
        return ["Retry with narrower candidate inputs or response_mode='full' for diagnostics."]
    return []


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


def _recovery_commands(
    request: RelatedEvidenceCandidatesRequest,
    provider_status: list[LiteratureProviderStatus],
) -> list[dict[str, Any]]:
    if not any(
        status.provider == "citation_graph"
        and status.operation == "candidate_neighbors"
        and status.retryable
        for status in provider_status
    ):
        return []
    return [
        {
            "tool": "pubtator.find_related_evidence_candidates",
            "arguments": {
                **request.model_dump(mode="json", exclude_none=True),
                "include_citation_neighbors": False,
            },
        }
    ]
