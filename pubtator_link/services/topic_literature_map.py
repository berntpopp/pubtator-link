"""Topic-level literature map orchestration service."""

from __future__ import annotations

import asyncio
import re
import time
from collections import Counter
from collections.abc import Awaitable, Sequence
from typing import Any, Protocol

from pubtator_link.models.literature_graph import (
    LiteratureCandidateSummary,
    LiteratureEntity,
    LiteratureGraphEdge,
    LiteratureGraphNode,
    LiteratureGraphProvenance,
    LiteraturePaper,
    LiteratureProviderStatus,
    LiteratureProviderStatusValue,
    LiteratureQueryRelevance,
    ProviderWarning,
    PublicationCitationGraphRequest,
    RelatedEvidenceCandidatesRequest,
    TopicLiteratureMapRequest,
    TopicLiteratureMapResponse,
    TopicLiteratureMapSummary,
    dedupe_edges,
    dedupe_papers,
)
from pubtator_link.services.literature_graph_compact import (
    TOPIC_RANKING_VERSION,
    candidate_summary,
    coalesced_provider_warnings,
    compact_author_summary,
    graph_budget_bytes,
    graph_detail_next_commands,
    graph_payload_json_bytes,
    graph_request_metadata,
    intent_flags_for_query,
    json_size_class,
    mark_graph_payload_truncated,
    normalize_query_text,
)
from pubtator_link.services.literature_paper_resolution import (
    merge_literature_availability,
    paper_from_publication_metadata,
)
from pubtator_link.services.publication_metadata import lookup_metadata_batched

TOPIC_STAGE_CONCURRENCY = 4


class TopicSearchClient(Protocol):
    """Search behavior needed to collect seed PMIDs."""

    async def search_publications(
        self,
        text: str,
        *,
        page: int = 1,
        sort: str | None = None,
    ) -> dict[str, Any]:
        """Search publications and return PubTator-style result dictionaries."""


class TopicLiteratureMapService:
    """Build bounded topic maps from seed PMIDs, metadata, citations, and related candidates."""

    def __init__(
        self,
        *,
        search_client: TopicSearchClient,
        metadata_service: Any,
        citation_graph_service: Any,
        related_evidence_service: Any,
    ) -> None:
        self.search_client = search_client
        self.metadata_service = metadata_service
        self.citation_graph_service = citation_graph_service
        self.related_evidence_service = related_evidence_service

    async def build_map(self, request: TopicLiteratureMapRequest) -> TopicLiteratureMapResponse:
        """Return a bounded literature graph for an explicit PMID set or topic query."""
        warnings: list[ProviderWarning] = []
        provider_status: list[LiteratureProviderStatus] = []
        deadline = _deadline_from_timeout_ms(request.timeout_ms)
        seed_pmids = await self._seed_pmids(request, warnings, provider_status, deadline)
        papers_by_pmid, entities_by_pmid = await self._metadata_papers(
            seed_pmids,
            include_entities=request.include_pubtator_entities,
            warnings=warnings,
            provider_status=provider_status,
            operation="seed_metadata",
            deadline=deadline,
        )
        papers: list[LiteraturePaper] = [
            papers_by_pmid.get(pmid, LiteraturePaper(pmid=pmid)) for pmid in seed_pmids
        ]
        edges: list[LiteratureGraphEdge] = []
        candidate_pmids: list[str] = []
        accessible_candidates: list[LiteraturePaper] = []
        remaining_neighbors = dict.fromkeys(seed_pmids, request.max_neighbors_per_paper)

        if request.include_citations:
            (
                citation_papers,
                citation_edges,
                citation_pmids,
                remaining_neighbors,
            ) = await self._citation_neighbors(
                seed_pmids=seed_pmids,
                remaining_neighbors=remaining_neighbors,
                request=request,
                warnings=warnings,
                provider_status=provider_status,
                deadline=_stage_deadline(deadline, request.citation_graph_timeout_ms),
            )
            papers.extend(citation_papers)
            edges.extend(citation_edges)
            candidate_pmids.extend(citation_pmids)

        if request.include_related_candidates and _deadline_exhausted(deadline):
            provider_status.append(
                _topic_provider_status(
                    "related_evidence",
                    "candidate_enrichment",
                    "skipped",
                    message="Skipped because the topic map timeout budget was exhausted.",
                )
            )
        elif request.include_related_candidates:
            related_papers, related_edges, related_pmids = await self._related_candidates(
                seed_pmids=seed_pmids,
                request=request,
                remaining_neighbors=remaining_neighbors,
                warnings=warnings,
                provider_status=provider_status,
                deadline=_stage_deadline(deadline, request.related_evidence_timeout_ms),
            )
            papers.extend(related_papers)
            edges.extend(related_edges)
            candidate_pmids.extend(related_pmids)
            accessible_candidates.extend(
                [paper for paper in related_papers if _has_full_text(paper)]
            )

        missing_metadata_pmids = [
            pmid
            for pmid in _dedupe(candidate_pmids)
            if pmid not in papers_by_pmid and pmid not in seed_pmids
        ]
        if missing_metadata_pmids and _deadline_exhausted(deadline):
            provider_status.append(
                _topic_provider_status(
                    "pubmed_metadata",
                    "metadata_backfill",
                    "skipped",
                    len(missing_metadata_pmids),
                    message="Skipped because the topic map timeout budget was exhausted.",
                )
            )
        elif missing_metadata_pmids:
            backfill_papers, backfill_entities = await self._metadata_papers(
                missing_metadata_pmids,
                include_entities=request.include_pubtator_entities,
                warnings=warnings,
                provider_status=provider_status,
                operation="metadata_backfill",
                deadline=_stage_deadline(deadline, request.metadata_backfill_timeout_ms),
            )
            papers_by_pmid.update(backfill_papers)
            entities_by_pmid.update(backfill_entities)
            papers.extend(
                papers_by_pmid[pmid] for pmid in missing_metadata_pmids if pmid in papers_by_pmid
            )

        papers = [_prefer_metadata_paper(paper, papers_by_pmid) for paper in papers]
        if request.include_authors:
            author_edges = _author_edges(dedupe_papers(papers))
            edges.extend(author_edges)
        if request.include_pubtator_entities:
            edges.extend(_entity_edges(dedupe_papers(papers), entities_by_pmid))

        deduped_papers = dedupe_papers(papers)
        deduped_edges = dedupe_edges(edges)
        nodes = _nodes(deduped_papers, request.include_authors, entities_by_pmid)
        summary = _summary(
            papers=deduped_papers,
            edges=deduped_edges,
            seed_pmids=seed_pmids,
            candidate_pmids=_dedupe(candidate_pmids),
            accessible_candidates=dedupe_papers(accessible_candidates),
            query=request.query,
            bias_toward=request.bias_toward,
        )
        ranked_candidates = rank_topic_candidates(
            deduped_papers,
            query=request.query,
            seed_pmids=seed_pmids,
            candidate_pmids=_dedupe(candidate_pmids),
            accessible_pmids=[paper.pmid for paper in accessible_candidates if paper.pmid],
            bias_toward=request.bias_toward,
        )
        recommended_next_pmids = _recommended_next_pmids(ranked_candidates, seed_pmids)
        recommended_next_candidates = _recommended_next_candidates(
            ranked_candidates,
            recommended_next_pmids,
        )
        accessible_full_text_pmids = _accessible_full_text_pmids(ranked_candidates)
        closed_central_pmids = _closed_central_pmids(ranked_candidates, summary)
        bias_score_by_pmid = _bias_score_by_pmid(ranked_candidates)
        demoted_candidate_pmids, demoted_reasons_by_pmid = _demoted_candidates(
            ranked_candidates,
            seed_pmids=seed_pmids,
            max_demoted=request.max_demoted,
            include_demoted=request.include_demoted,
        )
        hints = _retrieval_hints(recommended_next_pmids)
        response_nodes = nodes
        response_edges = deduped_edges
        response_summary = summary
        top_candidates = _top_actionable_candidates(ranked_candidates)[: request.max_candidates]
        omitted_counts: dict[str, int] = {}
        graph_inspection_hint: str | None = None

        if request.response_mode == "compact":
            response_nodes = []
            response_edges = []
            response_summary = _compact_summary(summary, recommended_next_pmids)
            compact_candidates, omitted_doi_only = _compact_actionable_topic_candidates(
                ranked_candidates
            )
            top_candidates = compact_candidates[: request.max_candidates]
            omitted_counts = {
                "nodes": len(nodes),
                "edges": len(deduped_edges),
                "summary_papers": max(
                    0,
                    _summary_paper_count(summary) - _summary_paper_count(response_summary),
                ),
                "top_candidates": max(0, len(ranked_candidates) - len(top_candidates)),
            }
            if omitted_doi_only:
                omitted_counts["doi_only_unresolved"] = omitted_doi_only
            if nodes or deduped_edges:
                graph_inspection_hint = (
                    "Use response_mode='nodes_edges' to inspect omitted graph nodes and edges."
                )
        elif request.response_mode == "nodes_edges":
            response_nodes = nodes[: request.max_graph_nodes]
            response_edges = deduped_edges[: request.max_graph_edges]
            response_summary = _summary_without_papers(summary, recommended_next_pmids)
            top_candidates = []
            omitted_counts = {
                "nodes": max(0, len(nodes) - len(response_nodes)),
                "edges": max(0, len(deduped_edges) - len(response_edges)),
                "summary_papers": _summary_paper_count(summary),
                "top_candidates": len(ranked_candidates),
            }

        meta = graph_request_metadata(
            tool_name="pubtator.build_topic_literature_map",
            request=request,
            source_versions={
                "pubtator_search": "live",
                "pubmed": "live",
                "citation_graph": "live",
                "related_evidence": "live",
            },
        ).model_copy(
            update={
                "truncated": any(count > 0 for count in omitted_counts.values()),
                "omitted_counts": omitted_counts,
                "ranking_version": TOPIC_RANKING_VERSION,
                "warnings": coalesced_provider_warnings(warnings),
                "next_commands": [
                    *graph_detail_next_commands(
                        tool_name="pubtator.build_topic_literature_map",
                        request=request,
                        modes=("full", "nodes_edges"),
                    ),
                    *_topic_map_recovery_commands(request, provider_status),
                    *hints,
                ],
                "provider_status": provider_status,
            }
        )
        response = TopicLiteratureMapResponse(
            query=request.query,
            seed_pmids=seed_pmids,
            summary=response_summary,
            nodes=response_nodes,
            edges=response_edges,
            response_mode=request.response_mode,
            top_candidates=top_candidates,
            recommended_next_pmids=recommended_next_pmids,
            recommended_next_candidates=recommended_next_candidates,
            accessible_full_text_pmids=accessible_full_text_pmids,
            closed_central_pmids=closed_central_pmids,
            demoted_candidate_pmids=demoted_candidate_pmids,
            demoted_reasons_by_pmid=demoted_reasons_by_pmid,
            bias_score_by_pmid=bias_score_by_pmid,
            provider_status=provider_status,
            omitted_counts=omitted_counts,
            graph_inspection_hint=graph_inspection_hint,
            candidate_retrieval_hints=hints,
            _meta=meta,
        )
        response = _enforce_topic_map_budget(response)
        response.meta.response_size_class = json_size_class(response.model_dump(by_alias=True))
        return response

    async def _seed_pmids(
        self,
        request: TopicLiteratureMapRequest,
        warnings: list[ProviderWarning],
        provider_status: list[LiteratureProviderStatus],
        deadline: float | None,
    ) -> list[str]:
        seed_pmids: list[str] = []
        if request.pmids:
            seed_pmids.extend(request.pmids)
        if request.query and len(seed_pmids) < request.max_seed_papers:
            try:
                raw = await _await_with_deadline(
                    self.search_client.search_publications(
                        request.query,
                        page=1,
                        sort="score desc",
                    ),
                    deadline,
                )
            except Exception as exc:
                warnings.append(_provider_failed_warning("pubtator_search", exc))
                provider_status.append(
                    _topic_provider_status(
                        "pubtator_search",
                        "seed_search",
                        "failed",
                        retryable=True,
                        message=_provider_exception_message(exc, "PubTator search"),
                    )
                )
                raw = {"results": []}
            else:
                result_count = len(_pmids_from_search(raw))
                provider_status.append(
                    _topic_provider_status(
                        "pubtator_search",
                        "seed_search",
                        "success" if result_count else "empty",
                        result_count,
                    )
                )
            search_pmids = _pmids_from_search(raw)
            needed = request.max_seed_papers - len(seed_pmids)
            seed_pmids.extend(
                await self._screen_query_seed_pmids(
                    search_pmids,
                    request=request,
                    limit=needed,
                    warnings=warnings,
                    provider_status=provider_status,
                    deadline=deadline,
                )
            )
        return _dedupe(seed_pmids)[: request.max_seed_papers]

    async def _screen_query_seed_pmids(
        self,
        pmids: list[str],
        *,
        request: TopicLiteratureMapRequest,
        limit: int,
        warnings: list[ProviderWarning],
        provider_status: list[LiteratureProviderStatus],
        deadline: float | None,
    ) -> list[str]:
        if not pmids or limit <= 0:
            return []
        screening_pmids = _dedupe(pmids)[: min(len(pmids), max(limit * 3, limit))]
        papers_by_pmid, _entities = await self._metadata_papers(
            screening_pmids,
            include_entities=False,
            warnings=warnings,
            provider_status=provider_status,
            operation="seed_screening",
            deadline=deadline,
        )
        if not papers_by_pmid:
            return screening_pmids[:limit]
        query_terms = _query_terms(request.query)
        intents = intent_flags_for_query(request.query)
        bias: set[str] = set(request.bias_toward or [])
        rank_by_pmid: dict[str, tuple[float, int]] = {}
        for index, pmid in enumerate(screening_pmids):
            paper = papers_by_pmid.get(pmid, LiteraturePaper(pmid=pmid))
            score, _reasons, demotions, _matched = _topic_candidate_score(
                paper=paper,
                query_terms=query_terms,
                intents=intents,
                seed_set=set(),
                candidate_set={pmid},
                accessible_set=set(),
                bias_toward=bias,
            )
            if "conference_abstract_collection" in demotions:
                score -= 8.0
            if "off_topic_title" in demotions:
                score -= 6.0
            rank_by_pmid[pmid] = (score, index)
        return sorted(
            screening_pmids,
            key=lambda pmid: (-rank_by_pmid[pmid][0], rank_by_pmid[pmid][1]),
        )[:limit]

    async def _metadata_papers(
        self,
        pmids: Sequence[str],
        *,
        include_entities: bool,
        warnings: list[ProviderWarning],
        provider_status: list[LiteratureProviderStatus] | None = None,
        operation: str = "metadata_lookup",
        deadline: float | None = None,
    ) -> tuple[dict[str, LiteraturePaper], dict[str, list[LiteratureEntity]]]:
        if not pmids:
            return {}, {}
        try:
            response = await _await_with_deadline(
                lookup_metadata_batched(
                    self.metadata_service,
                    pmids,
                    include_mesh=include_entities,
                    include_publication_types=True,
                    include_citations="none",
                    include_coverage=True,
                ),
                deadline,
            )
        except Exception as exc:
            warnings.append(_provider_failed_warning("pubmed_metadata", exc))
            if provider_status is not None:
                provider_status.append(
                    _topic_provider_status(
                        "pubmed_metadata",
                        operation,
                        "failed",
                        retryable=True,
                        message=_provider_exception_message(exc, "PubMed metadata"),
                    )
                )
            return {}, {}
        for warning in _metadata_response_warnings(response):
            warnings.append(
                ProviderWarning(
                    provider="pubmed_metadata",
                    status="provider_failed",
                    retryable=True,
                    message=f"PubMed metadata warning: {warning}",
                )
            )
        if response.failed_pmids:
            warnings.append(
                ProviderWarning(
                    provider="pubmed_metadata",
                    status="provider_failed",
                    retryable=True,
                    message=f"Metadata lookup failed for {len(response.failed_pmids)} PMID(s).",
                )
            )
        if provider_status is not None:
            status: LiteratureProviderStatusValue
            if response.metadata and response.failed_pmids:
                status = "partial"
            elif response.metadata:
                status = "success"
            elif response.failed_pmids:
                status = "failed"
            else:
                status = "empty"
            provider_status.append(
                _topic_provider_status(
                    "pubmed_metadata",
                    operation,
                    status,
                    len(response.metadata),
                    retryable=bool(response.failed_pmids),
                    message=(
                        f"failed_pmids={len(response.failed_pmids)}"
                        if response.failed_pmids
                        else None
                    ),
                )
            )
        return (
            {metadata.pmid: _paper_from_metadata(metadata) for metadata in response.metadata},
            {
                metadata.pmid: _entities_from_metadata(metadata)
                for metadata in response.metadata
                if include_entities
            },
        )

    async def _citation_neighbors(
        self,
        *,
        seed_pmids: list[str],
        remaining_neighbors: dict[str, int],
        request: TopicLiteratureMapRequest,
        warnings: list[ProviderWarning],
        provider_status: list[LiteratureProviderStatus],
        deadline: float | None,
    ) -> tuple[list[LiteraturePaper], list[LiteratureGraphEdge], list[str], dict[str, int]]:
        semaphore = asyncio.Semaphore(TOPIC_STAGE_CONCURRENCY)

        async def collect_seed(
            seed_pmid: str,
        ) -> tuple[
            str,
            int,
            list[LiteraturePaper],
            list[LiteratureGraphEdge],
            list[str],
            Exception | None,
        ]:
            remaining = remaining_neighbors.get(seed_pmid, 0)
            if remaining <= 0:
                return seed_pmid, remaining, [], [], [], None
            try:
                async with semaphore:
                    graph = await _await_with_deadline(
                        self.citation_graph_service.get_citation_graph(
                            PublicationCitationGraphRequest(
                                pmid=seed_pmid,
                                direction="both",
                                max_results=remaining,
                                query=request.query,
                            )
                        ),
                        deadline,
                    )
            except Exception as exc:
                return seed_pmid, remaining, [], [], [], exc
            papers: list[LiteraturePaper] = []
            edges: list[LiteratureGraphEdge] = []
            candidate_pmids: list[str] = []
            for paper in graph.references:
                if remaining <= 0:
                    break
                papers.append(paper)
                candidate_pmids.extend([paper.pmid] if paper.pmid else [])
                edges.append(
                    _edge(
                        source=LiteraturePaper(pmid=seed_pmid).key,
                        target=paper.key,
                        edge_type="cites",
                        reason="reference_neighbor",
                        provider="citation_graph",
                    )
                )
                remaining -= 1
            for paper in graph.cited_by:
                if remaining <= 0:
                    break
                papers.append(paper)
                candidate_pmids.extend([paper.pmid] if paper.pmid else [])
                edges.append(
                    _edge(
                        source=LiteraturePaper(pmid=seed_pmid).key,
                        target=paper.key,
                        edge_type="cited_by",
                        reason="cited_by_neighbor",
                        provider="citation_graph",
                    )
                )
                remaining -= 1
            remaining_neighbors[seed_pmid] = remaining
            return seed_pmid, remaining, papers, edges, candidate_pmids, None

        results = await asyncio.gather(*(collect_seed(seed_pmid) for seed_pmid in seed_pmids))
        papers: list[LiteraturePaper] = []
        edges: list[LiteratureGraphEdge] = []
        candidate_pmids: list[str] = []
        failed_count = 0
        failure_message: str | None = None
        for seed_pmid, remaining, seed_papers, seed_edges, seed_pmids, exc in results:
            if exc is not None:
                warnings.append(_provider_failed_warning("citation_graph", exc))
                failed_count += 1
                failure_message = _provider_exception_message(exc, "Citation graph")
                continue
            remaining_neighbors[seed_pmid] = remaining
            papers.extend(seed_papers)
            edges.extend(seed_edges)
            candidate_pmids.extend(seed_pmids)
        provider_status.append(
            _stage_provider_status(
                "citation_graph",
                "neighbor_enrichment",
                result_count=len(papers),
                failed_count=failed_count,
                failure_message=failure_message,
            )
        )
        return papers, edges, _dedupe(candidate_pmids), remaining_neighbors

    async def _related_candidates(
        self,
        *,
        seed_pmids: list[str],
        request: TopicLiteratureMapRequest,
        remaining_neighbors: dict[str, int],
        warnings: list[ProviderWarning],
        provider_status: list[LiteratureProviderStatus],
        deadline: float | None,
    ) -> tuple[list[LiteraturePaper], list[LiteratureGraphEdge], list[str]]:
        semaphore = asyncio.Semaphore(TOPIC_STAGE_CONCURRENCY)

        async def collect_seed(
            seed_pmid: str,
        ) -> tuple[
            str,
            int,
            list[LiteraturePaper],
            list[LiteratureGraphEdge],
            list[str],
            Exception | None,
        ]:
            remaining = remaining_neighbors.get(seed_pmid, 0)
            if remaining <= 0:
                return seed_pmid, remaining, [], [], [], None
            try:
                async with semaphore:
                    response = await _await_with_deadline(
                        self.related_evidence_service.find_candidates(
                            RelatedEvidenceCandidatesRequest(
                                pmid=seed_pmid,
                                max_results=remaining,
                                prefer_full_text=request.prefer_full_text,
                                include_pubtator_search=True,
                                include_citation_neighbors=False,
                                year_min=request.year_min,
                                year_max=request.year_max,
                            )
                        ),
                        deadline,
                    )
            except Exception as exc:
                return seed_pmid, remaining, [], [], [], exc
            papers: list[LiteraturePaper] = []
            edges: list[LiteratureGraphEdge] = []
            candidate_pmids: list[str] = []
            for candidate in response.candidates:
                if remaining <= 0:
                    break
                papers.append(candidate.paper)
                if candidate.paper.pmid:
                    candidate_pmids.append(candidate.paper.pmid)
                edges.append(
                    LiteratureGraphEdge(
                        source=LiteraturePaper(pmid=seed_pmid).key,
                        target=candidate.paper.key,
                        edge_type="related_by_elink",
                        weight=max(candidate.score, 1.0),
                        reasons=candidate.match_reasons or ["related_candidate"],
                        provenance=[
                            LiteratureGraphProvenance(provider="ncbi_elink", raw_status="related")
                        ],
                    )
                )
                remaining -= 1
            remaining_neighbors[seed_pmid] = remaining
            return seed_pmid, remaining, papers, edges, candidate_pmids, None

        results = await asyncio.gather(*(collect_seed(seed_pmid) for seed_pmid in seed_pmids))
        papers: list[LiteraturePaper] = []
        edges: list[LiteratureGraphEdge] = []
        candidate_pmids: list[str] = []
        failed_count = 0
        failure_message: str | None = None
        for seed_pmid, remaining, seed_papers, seed_edges, seed_pmids, exc in results:
            if exc is not None:
                warnings.append(_provider_failed_warning("related_evidence", exc))
                failed_count += 1
                failure_message = _provider_exception_message(exc, "Related evidence")
                continue
            remaining_neighbors[seed_pmid] = remaining
            papers.extend(seed_papers)
            edges.extend(seed_edges)
            candidate_pmids.extend(seed_pmids)
        provider_status.append(
            _stage_provider_status(
                "related_evidence",
                "candidate_enrichment",
                result_count=len(papers),
                failed_count=failed_count,
                failure_message=failure_message,
            )
        )
        return papers, edges, _dedupe(candidate_pmids)


def _pmids_from_search(raw: dict[str, Any]) -> list[str]:
    pmids: list[str] = []
    for item in raw.get("results", []):
        if isinstance(item, dict):
            pmid = item.get("pmid") or item.get("id")
            if pmid:
                pmids.append(str(pmid))
    return pmids


def _paper_from_metadata(metadata: Any) -> LiteraturePaper:
    return paper_from_publication_metadata(metadata, include_authors=True)


def _entities_from_metadata(metadata: Any) -> list[LiteratureEntity]:
    return [
        LiteratureEntity(
            entity_id=f"mesh:{heading.casefold()}",
            entity_type="mesh_heading",
            name=heading,
            provenance=[LiteratureGraphProvenance(provider="pubmed_metadata")],
        )
        for heading in getattr(metadata, "mesh_headings", [])
        if heading
    ]


def _metadata_response_warnings(response: Any) -> list[str]:
    raw_warnings = response.meta.get("warnings", [])
    if isinstance(raw_warnings, str):
        return [raw_warnings]
    if isinstance(raw_warnings, list):
        return [warning for warning in raw_warnings if isinstance(warning, str) and warning]
    return []


def _prefer_metadata_paper(
    paper: LiteraturePaper,
    metadata_by_pmid: dict[str, LiteraturePaper],
) -> LiteraturePaper:
    if not paper.pmid or paper.pmid not in metadata_by_pmid:
        return paper
    metadata_paper = metadata_by_pmid[paper.pmid]
    if _paper_richness(metadata_paper) > _paper_richness(paper):
        return _merge_missing_paper_fields(metadata_paper, paper)
    return _merge_missing_paper_fields(paper, metadata_paper)


def _merge_missing_paper_fields(
    primary: LiteraturePaper, fallback: LiteraturePaper
) -> LiteraturePaper:
    return merge_literature_availability(primary, fallback)


def _paper_richness(paper: LiteraturePaper) -> int:
    score = 0
    score += sum(
        bool(value)
        for value in (
            paper.doi,
            paper.pmcid,
            paper.openalex_id,
            paper.title,
            paper.journal,
            paper.year,
        )
    )
    score += min(len(paper.publication_types), 3)
    score += min(len(paper.authors), 5)
    score += int(paper.availability.has_pmc_full_text)
    score += int(paper.availability.is_open_access)
    score += int(paper.availability.has_pdf)
    score += int(bool(paper.availability.full_text_url))
    return score


def _author_edges(papers: list[LiteraturePaper]) -> list[LiteratureGraphEdge]:
    edges: list[LiteratureGraphEdge] = []
    for paper in papers:
        for author in paper.authors:
            edges.append(
                _edge(
                    source=paper.key,
                    target=author.key,
                    edge_type="authored_by",
                    reason="metadata_author",
                    provider="pubmed_metadata",
                )
            )
    return edges


def _entity_edges(
    papers: list[LiteraturePaper],
    entities_by_pmid: dict[str, list[LiteratureEntity]],
) -> list[LiteratureGraphEdge]:
    edges: list[LiteratureGraphEdge] = []
    for paper in papers:
        if not paper.pmid:
            continue
        for entity in entities_by_pmid.get(paper.pmid, []):
            edges.append(
                _edge(
                    source=paper.key,
                    target=entity.key,
                    edge_type="mentions_entity",
                    reason="metadata_mesh_heading",
                    provider="pubmed_metadata",
                )
            )
    return edges


def _nodes(
    papers: list[LiteraturePaper],
    include_authors: bool,
    entities_by_pmid: dict[str, list[LiteratureEntity]],
) -> list[LiteratureGraphNode]:
    nodes: dict[str, LiteratureGraphNode] = {}
    for paper in papers:
        nodes[paper.key] = LiteratureGraphNode(node_type="paper", paper=paper)
        if include_authors:
            for author in paper.authors:
                nodes.setdefault(
                    author.key,
                    LiteratureGraphNode(node_type="author", author=author),
                )
        for entity in entities_by_pmid.get(paper.pmid or "", []):
            nodes.setdefault(
                entity.key,
                LiteratureGraphNode(node_type="entity", entity=entity),
            )
    return list(nodes.values())


def _summary(
    *,
    papers: list[LiteraturePaper],
    edges: list[LiteratureGraphEdge],
    seed_pmids: list[str],
    candidate_pmids: list[str],
    accessible_candidates: list[LiteraturePaper],
    query: str | None,
    bias_toward: Sequence[str] | None,
) -> TopicLiteratureMapSummary:
    paper_by_key = {paper.key: paper for paper in papers}
    seed_rank = {pmid: index for index, pmid in enumerate(seed_pmids)}
    candidate_set = set(candidate_pmids)
    accessible_set = {paper.pmid for paper in accessible_candidates if paper.pmid}
    query_terms = _query_terms(query)
    intents = intent_flags_for_query(query)
    bias = set(bias_toward or [])
    degree = Counter[str]()
    for edge in edges:
        if edge.edge_type not in {"cites", "cited_by", "related_by_elink"}:
            continue
        degree[edge.source] += 1
        degree[edge.target] += 1

    def centrality_key(paper: LiteraturePaper) -> tuple[float, int, int, int, int, str]:
        score, _rank_reasons, demotion_reasons, _matched_terms = _topic_candidate_score(
            paper=paper,
            query_terms=query_terms,
            intents=intents,
            seed_set=set(seed_pmids),
            candidate_set=candidate_set,
            accessible_set=accessible_set,
            bias_toward=bias,
        )
        if "low_query_overlap" in demotion_reasons:
            score -= 5.0
        if "conference_abstract_collection" in demotion_reasons:
            score -= 8.0
        return (
            -score,
            paper.pmid not in seed_rank,
            -degree[paper.key],
            seed_rank.get(paper.pmid or "", len(seed_rank)),
            -(paper.year or 0),
            paper.pmid or paper.key,
        )

    central_papers = sorted(
        papers,
        key=centrality_key,
    )[:10]
    recent_connected_papers = sorted(
        [paper for paper in papers if degree[paper.key] > 0],
        key=lambda paper: (-(paper.year or 0), paper.pmid or paper.key),
    )[:10]
    author_counts: Counter[str] = Counter()
    for paper in papers:
        author_counts.update(author.name for author in paper.authors)

    recommended_next_pmids = [
        pmid
        for pmid in _dedupe(candidate_pmids)
        if pmid not in seed_pmids and f"paper:pmid:{pmid}" in paper_by_key
    ][:20]
    if not recommended_next_pmids:
        recommended_next_pmids = [
            paper.pmid for paper in central_papers if paper.pmid and paper.pmid not in seed_pmids
        ][:20]

    return TopicLiteratureMapSummary(
        central_papers=central_papers,
        recent_connected_papers=recent_connected_papers,
        bridge_papers=[
            paper
            for paper in central_papers
            if paper.pmid and paper.pmid not in seed_pmids and degree[paper.key] > 1
        ][:10],
        dominant_author_groups=[name for name, _count in author_counts.most_common(10)],
        accessible_full_text_candidates=accessible_candidates[:10],
        closed_central_sources=[paper for paper in central_papers if not _has_full_text(paper)][
            :10
        ],
        recommended_next_pmids=recommended_next_pmids,
    )


def _retrieval_hints(pmids: list[str]) -> list[dict[str, Any]]:
    if not pmids:
        return []
    return [
        {
            "tool": "pubtator.get_publication_passages",
            "arguments": {"pmids": pmids},
        },
        {
            "tool": "pubtator.index_review_evidence",
            "arguments": {"pmids": pmids},
        },
    ]


def _recommended_next_pmids(
    candidates: list[LiteratureCandidateSummary],
    seed_pmids: list[str],
) -> list[str]:
    seed_set = set(seed_pmids)
    weak_reasons = {"missing_pmid", "doi_only_unresolved", "low_query_overlap"}
    pmid_candidates = [
        candidate for candidate in candidates if candidate.pmid and candidate.pmid not in seed_set
    ]
    stronger_candidates = [
        candidate
        for candidate in pmid_candidates
        if not weak_reasons.intersection(candidate.demotion_reasons)
    ]
    selected = stronger_candidates if stronger_candidates else pmid_candidates
    return _dedupe([candidate.pmid or "" for candidate in selected])[:20]


def _recommended_next_candidates(
    candidates: list[LiteratureCandidateSummary],
    recommended_pmids: list[str],
) -> list[LiteratureCandidateSummary]:
    recommended_set = set(recommended_pmids)
    return [candidate for candidate in candidates if candidate.pmid in recommended_set][
        : len(recommended_pmids)
    ]


def _top_actionable_candidates(
    candidates: list[LiteratureCandidateSummary],
) -> list[LiteratureCandidateSummary]:
    actionable = [candidate for candidate in candidates if not candidate.demotion_reasons]
    return actionable if actionable else candidates


def _accessible_full_text_pmids(candidates: list[LiteratureCandidateSummary]) -> list[str]:
    return _dedupe(
        [
            candidate.pmid or ""
            for candidate in candidates
            if candidate.pmid and candidate.access == "full_text"
        ]
    )


def _closed_central_pmids(
    candidates: list[LiteratureCandidateSummary],
    summary: TopicLiteratureMapSummary,
) -> list[str]:
    central_pmids = {paper.pmid for paper in summary.closed_central_sources if paper.pmid}
    return _dedupe(
        [
            candidate.pmid or ""
            for candidate in candidates
            if candidate.pmid in central_pmids
            and candidate.access not in {"full_text", "open_access"}
        ]
    )


def _demoted_candidates(
    candidates: list[LiteratureCandidateSummary],
    *,
    seed_pmids: list[str],
    max_demoted: int,
    include_demoted: bool,
) -> tuple[list[str], dict[str, list[str]]]:
    if not include_demoted or max_demoted == 0:
        return [], {}
    seed_set = set(seed_pmids)
    demoted = [
        candidate
        for candidate in candidates
        if candidate.pmid and candidate.pmid not in seed_set and candidate.demotion_reasons
    ][:max_demoted]
    pmids = [candidate.pmid or "" for candidate in demoted]
    return pmids, {
        candidate.pmid or "": candidate.demotion_reasons for candidate in demoted if candidate.pmid
    }


def _bias_score_by_pmid(candidates: list[LiteratureCandidateSummary]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for candidate in candidates:
        if not candidate.pmid or candidate.relevance_to_query is None:
            continue
        matched_intents = candidate.relevance_to_query.matched_intents
        if matched_intents:
            scores[candidate.pmid] = min(1.0, len(matched_intents) / 3)
    return scores


def _compact_actionable_topic_candidates(
    candidates: list[LiteratureCandidateSummary],
) -> tuple[list[LiteratureCandidateSummary], int]:
    actionable = [
        candidate for candidate in candidates if candidate.pmid and not candidate.demotion_reasons
    ]
    if not actionable:
        actionable = [candidate for candidate in candidates if candidate.pmid]
    omitted_doi_only = sum(1 for candidate in candidates if candidate.doi and not candidate.pmid)
    return actionable, omitted_doi_only


def _summary_without_papers(
    summary: TopicLiteratureMapSummary,
    recommended_next_pmids: list[str],
) -> TopicLiteratureMapSummary:
    return TopicLiteratureMapSummary(
        central_papers=[],
        recent_connected_papers=[],
        bridge_papers=[],
        dominant_author_groups=summary.dominant_author_groups,
        accessible_full_text_candidates=[],
        closed_central_sources=[],
        recommended_next_pmids=recommended_next_pmids,
    )


def _compact_summary(
    summary: TopicLiteratureMapSummary,
    recommended_next_pmids: list[str],
) -> TopicLiteratureMapSummary:
    return TopicLiteratureMapSummary(
        central_papers=[_compact_paper(paper) for paper in summary.central_papers if paper.pmid][
            :5
        ],
        recent_connected_papers=[
            _compact_paper(paper) for paper in summary.recent_connected_papers if paper.pmid
        ][:5],
        bridge_papers=[_compact_paper(paper) for paper in summary.bridge_papers if paper.pmid][:5],
        dominant_author_groups=summary.dominant_author_groups,
        accessible_full_text_candidates=[
            _compact_paper(paper) for paper in summary.accessible_full_text_candidates if paper.pmid
        ][:5],
        closed_central_sources=[
            _compact_paper(paper) for paper in summary.closed_central_sources if paper.pmid
        ][:5],
        recommended_next_pmids=recommended_next_pmids,
    )


def _compact_paper(paper: LiteraturePaper) -> LiteraturePaper:
    author_label, author_count = compact_author_summary(paper.authors)
    return paper.model_copy(
        update={
            "authors": [],
            "author_summary": author_label,
            "author_count": author_count,
        }
    )


def _summary_paper_count(summary: TopicLiteratureMapSummary) -> int:
    return (
        len(summary.central_papers)
        + len(summary.recent_connected_papers)
        + len(summary.bridge_papers)
        + len(summary.accessible_full_text_candidates)
        + len(summary.closed_central_sources)
    )


def _enforce_topic_map_budget(response: TopicLiteratureMapResponse) -> TopicLiteratureMapResponse:
    budget = graph_budget_bytes(response.response_mode)
    if budget is None:
        return response
    if graph_payload_json_bytes(response) <= budget:
        return response

    omitted: dict[str, int] = {}
    compacted = response.model_copy(
        update={
            "demoted_candidate_pmids": [],
            "demoted_reasons_by_pmid": {},
            "candidate_retrieval_hints": response.candidate_retrieval_hints[:1],
        }
    )
    if response.demoted_candidate_pmids:
        omitted["demoted_candidates"] = len(response.demoted_candidate_pmids)
    compacted, dropped = _drop_topic_candidates_to_budget(compacted, budget=budget)
    if dropped:
        omitted["top_candidates"] = omitted.get("top_candidates", 0) + dropped
    return compacted.model_copy(
        update={
            "meta": mark_graph_payload_truncated(
                compacted.meta,
                omitted_counts=omitted,
                budget_bytes=budget,
            )
        }
    )


def _drop_topic_candidates_to_budget(
    response: TopicLiteratureMapResponse,
    *,
    budget: int,
) -> tuple[TopicLiteratureMapResponse, int]:
    overage = graph_payload_json_bytes(response) - budget
    if overage <= 0:
        return response, 0
    reclaimed = 0
    dropped = 0
    for candidate in reversed(response.top_candidates):
        reclaimed += graph_payload_json_bytes(candidate)
        dropped += 1
        if reclaimed >= overage:
            break
    trimmed = response.model_copy(
        update={"top_candidates": response.top_candidates[: len(response.top_candidates) - dropped]}
    )
    if graph_payload_json_bytes(trimmed) <= budget:
        return trimmed, dropped
    return trimmed.model_copy(update={"top_candidates": []}), len(response.top_candidates)


def _edge(
    *,
    source: str,
    target: str,
    edge_type: str,
    reason: str,
    provider: str,
) -> LiteratureGraphEdge:
    return LiteratureGraphEdge(
        source=source,
        target=target,
        edge_type=edge_type,  # type: ignore[arg-type]
        reasons=[reason],
        provenance=[LiteratureGraphProvenance(provider=provider)],
    )


def _dedupe(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _has_full_text(paper: LiteraturePaper) -> bool:
    return paper.status == "resolved_full_text_candidate" or paper.availability.has_pmc_full_text


def _deadline_from_timeout_ms(timeout_ms: int) -> float | None:
    if timeout_ms <= 0:
        return None
    return time.monotonic() + (timeout_ms / 1000)


def _stage_deadline(global_deadline: float | None, timeout_ms: int | None) -> float | None:
    stage_deadline = time.monotonic() + (timeout_ms / 1000) if timeout_ms is not None else None
    if global_deadline is None:
        return stage_deadline
    if stage_deadline is None:
        return global_deadline
    return min(global_deadline, stage_deadline)


def _deadline_exhausted(deadline: float | None) -> bool:
    return deadline is not None and deadline <= time.monotonic()


async def _await_with_deadline(awaitable: Awaitable[Any], deadline: float | None) -> Any:
    if deadline is None:
        return await awaitable
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise TimeoutError("topic map stage timed out before start")
    return await asyncio.wait_for(awaitable, timeout=remaining)


def _provider_exception_message(exc: Exception, label: str) -> str:
    if isinstance(exc, TimeoutError):
        return f"{label} timed out before topic map completed; retry with narrower inputs or disable this stage."
    return str(exc) or exc.__class__.__name__


def _topic_provider_status(
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


def _stage_provider_status(
    provider: str,
    operation: str,
    *,
    result_count: int,
    failed_count: int,
    failure_message: str | None,
) -> LiteratureProviderStatus:
    status: LiteratureProviderStatusValue
    if failed_count and result_count:
        status = "partial"
    elif failed_count:
        status = "failed"
    elif result_count:
        status = "success"
    else:
        status = "empty"
    message = failure_message
    if failed_count and failure_message and result_count:
        message = f"{failure_message} Partial results returned; failed_seed_pmids={failed_count}."
    elif failed_count and not failure_message:
        message = f"failed_seed_pmids={failed_count}"
    return _topic_provider_status(
        provider,
        operation,
        status,
        result_count,
        retryable=bool(failed_count),
        message=message,
    )


def _topic_map_recovery_commands(
    request: TopicLiteratureMapRequest,
    provider_status: list[LiteratureProviderStatus],
) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    request_args = request.model_dump(mode="json", exclude_none=True)
    if any(
        status.provider == "citation_graph"
        and status.operation == "neighbor_enrichment"
        and status.retryable
        for status in provider_status
    ):
        commands.append(
            {
                "tool": "pubtator.build_topic_literature_map",
                "arguments": {**request_args, "include_citations": False},
            }
        )
    if any(
        status.provider == "related_evidence"
        and status.operation == "candidate_enrichment"
        and status.retryable
        for status in provider_status
    ):
        commands.append(
            {
                "tool": "pubtator.build_topic_literature_map",
                "arguments": {**request_args, "include_related_candidates": False},
            }
        )
    return commands


def _provider_failed_warning(provider: str, exc: Exception) -> ProviderWarning:
    return ProviderWarning(
        provider=provider,
        status="provider_failed",
        retryable=True,
        message=_provider_exception_message(exc, provider),
    )


def rank_topic_candidates(
    papers: list[LiteraturePaper],
    *,
    query: str | None,
    seed_pmids: list[str],
    candidate_pmids: list[str],
    accessible_pmids: list[str],
    bias_toward: Sequence[str] | None = None,
) -> list[LiteratureCandidateSummary]:
    intents = intent_flags_for_query(query)
    query_terms = _query_terms(query)
    seed_set = set(seed_pmids)
    candidate_set = set(candidate_pmids)
    accessible_set = set(accessible_pmids)
    ranked: list[LiteratureCandidateSummary] = []
    for paper in dedupe_papers(papers):
        score, rank_reasons, demotion_reasons, matched_terms = _topic_candidate_score(
            paper=paper,
            query_terms=query_terms,
            intents=intents,
            seed_set=seed_set,
            candidate_set=candidate_set,
            accessible_set=accessible_set,
            bias_toward=set(bias_toward or []),
        )
        relevance = LiteratureQueryRelevance(
            score=max(0.0, min(1.0, score / 20.0)),
            matched_terms=matched_terms[:8],
            matched_intents=sorted(intents),
            reasons=rank_reasons[:8],
        )
        ranked.append(
            candidate_summary(
                paper,
                score=score,
                relevance_to_query=relevance,
                rank_reasons=rank_reasons,
                demotion_reasons=demotion_reasons,
                source_tools=(
                    ["topic_search"]
                    if paper.pmid in seed_set
                    else ["topic_search", "related_evidence"]
                ),
            )
        )
    return sorted(
        ranked,
        key=lambda candidate: (
            -float(candidate.score or 0),
            int("missing_pmid" in candidate.demotion_reasons),
            int("low_query_overlap" in candidate.demotion_reasons),
            candidate.year or 0,
            candidate.pmid or candidate.doi or candidate.title or "",
        ),
        reverse=False,
    )


def _topic_candidate_score(
    *,
    paper: LiteraturePaper,
    query_terms: list[str],
    intents: set[str],
    seed_set: set[str],
    candidate_set: set[str],
    accessible_set: set[str],
    bias_toward: set[str],
) -> tuple[float, list[str], list[str], list[str]]:
    score = 1.0
    rank_reasons: list[str] = []
    demotion_reasons = _topic_demotion_reasons(paper)

    if paper.pmid:
        if paper.pmid in seed_set:
            score += 5.0
            rank_reasons.append("seed_paper")
        if paper.pmid in candidate_set:
            score += 3.0
            rank_reasons.append("candidate_paper")
        if paper.pmid in accessible_set:
            score += 2.0
            rank_reasons.append("accessible_full_text")
    else:
        demotion_reasons.append("missing_pmid")
        if paper.doi:
            demotion_reasons.append("doi_only_unresolved")

    searchable_text = normalize_query_text(
        " ".join(
            value
            for value in [
                paper.title or "",
                paper.journal or "",
                _publication_type_text(paper),
            ]
            if value
        )
    )
    matched_terms = [term for term in query_terms if term in searchable_text]
    if matched_terms:
        score += len(matched_terms) * 1.5
        rank_reasons.append("query_term_overlap")

    publication_type_text = _publication_type_text(paper)
    title = normalize_query_text(paper.title)
    if "guideline_intent" in intents and (
        "guideline" in publication_type_text
        or "recommendation" in title
        or "recommendations" in title
    ):
        score += 7.0
        rank_reasons.append("guideline_intent")
    if ("guideline" in bias_toward) and (
        "guideline" in publication_type_text or "recommendation" in title
    ):
        score += 3.0
        rank_reasons.append("guideline_bias")
    if "pediatric_intent" in intents and any(
        term in title for term in ("child", "children", "pediatric", "paediatric")
    ):
        score += 5.0
        rank_reasons.append("pediatric_intent")
    if ("pediatric" in bias_toward) and any(
        term in title for term in ("child", "children", "pediatric", "paediatric")
    ):
        score += 2.0
        rank_reasons.append("pediatric_bias")
    if "treatment_intent" in intents and any(
        term in title for term in ("colchicine", "treatment", "management")
    ):
        score += 2.5
        rank_reasons.append("treatment_intent")
    if "variant_intent" in intents and any(
        term in title for term in ("variant", "genotype", "phenotype")
    ):
        score += 1.5
        rank_reasons.append("variant_intent")

    if (
        query_terms
        and len(matched_terms) < 2
        and "conference_abstract_collection" not in demotion_reasons
    ):
        demotion_reasons.append("low_query_overlap")
    if paper.status == "resolved_metadata_only" and not paper.title:
        demotion_reasons.append("metadata_only")

    score -= _demotion_penalty(demotion_reasons)
    return score, _dedupe(rank_reasons), _dedupe(demotion_reasons), matched_terms


def _query_terms(query: str | None) -> list[str]:
    normalized = normalize_query_text(query)
    terms = re.findall(r"[a-z0-9]+", normalized)
    stop_words = {"and", "or", "the", "for", "with", "of", "in", "a", "an", "to"}
    return _dedupe([term for term in terms if len(term) > 1 and term not in stop_words])


def _publication_type_text(paper: LiteraturePaper) -> str:
    return normalize_query_text(" ".join(paper.publication_types))


def _topic_demotion_reasons(paper: LiteraturePaper) -> list[str]:
    text = " ".join(
        value
        for value in [paper.title or "", paper.journal or "", _publication_type_text(paper)]
        if value
    )
    normalized = normalize_query_text(text)
    reasons: list[str] = []
    if any(signal in normalized for signal in ("abstract", "meeting", "conference", "congress")):
        reasons.append("conference_abstract_collection")
    if "supplement" in normalized:
        reasons.append("supplement_collection")
    if "annual" in normalized:
        reasons.append("annual_review_collection")
    if any(signal in normalized for signal in ("veterinary", "highlights", "trisomy 8")):
        reasons.append("off_topic_title")
    return reasons


def _demotion_penalty(demotion_reasons: list[str]) -> float:
    penalties = {
        "missing_pmid": 4.0,
        "doi_only_unresolved": 1.0,
        "conference_abstract_collection": 2.0,
        "supplement_collection": 2.0,
        "annual_review_collection": 1.0,
        "off_topic_title": 4.0,
        "low_query_overlap": 4.0,
        "metadata_only": 1.0,
    }
    return sum(penalties[reason] for reason in demotion_reasons if reason in penalties)
