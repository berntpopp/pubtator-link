"""Topic-level literature map orchestration service."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from typing import Any, Protocol

from pubtator_link.models.literature_graph import (
    LiteratureAuthor,
    LiteratureAvailability,
    LiteratureCandidateSummary,
    LiteratureEntity,
    LiteratureGraphEdge,
    LiteratureGraphNode,
    LiteratureGraphProvenance,
    LiteratureGraphResponseMeta,
    LiteraturePaper,
    LiteraturePaperStatus,
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
from pubtator_link.models.publication_metadata import PublicationMetadataRequest
from pubtator_link.services.literature_graph_compact import (
    TOPIC_RANKING_VERSION,
    candidate_summary,
    coalesced_provider_warnings,
    intent_flags_for_query,
    json_size_class,
    normalize_query_text,
)


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
        seed_pmids = await self._seed_pmids(request, warnings)
        papers_by_pmid, entities_by_pmid = await self._metadata_papers(
            seed_pmids,
            include_entities=request.include_pubtator_entities,
            warnings=warnings,
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
                warnings=warnings,
            )
            papers.extend(citation_papers)
            edges.extend(citation_edges)
            candidate_pmids.extend(citation_pmids)

        if request.include_related_candidates:
            related_papers, related_edges, related_pmids = await self._related_candidates(
                seed_pmids=seed_pmids,
                request=request,
                remaining_neighbors=remaining_neighbors,
                warnings=warnings,
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
        if missing_metadata_pmids:
            backfill_papers, backfill_entities = await self._metadata_papers(
                missing_metadata_pmids,
                include_entities=request.include_pubtator_entities,
                warnings=warnings,
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
        accessible_full_text_pmids = _accessible_full_text_pmids(ranked_candidates)
        closed_central_pmids = _closed_central_pmids(ranked_candidates, summary)
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
        top_candidates = ranked_candidates[: request.max_candidates]
        omitted_counts: dict[str, int] = {}

        if request.response_mode == "compact":
            response_nodes = []
            response_edges = []
            response_summary = _summary_without_papers(summary, recommended_next_pmids)
            omitted_counts = {
                "nodes": len(nodes),
                "edges": len(deduped_edges),
                "summary_papers": _summary_paper_count(summary),
                "top_candidates": max(0, len(ranked_candidates) - len(top_candidates)),
            }
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

        response = TopicLiteratureMapResponse(
            query=request.query,
            seed_pmids=seed_pmids,
            summary=response_summary,
            nodes=response_nodes,
            edges=response_edges,
            response_mode=request.response_mode,
            top_candidates=top_candidates,
            recommended_next_pmids=recommended_next_pmids,
            accessible_full_text_pmids=accessible_full_text_pmids,
            closed_central_pmids=closed_central_pmids,
            demoted_candidate_pmids=demoted_candidate_pmids,
            demoted_reasons_by_pmid=demoted_reasons_by_pmid,
            provider_status=[],
            omitted_counts=omitted_counts,
            candidate_retrieval_hints=hints,
            _meta=LiteratureGraphResponseMeta(
                response_mode=request.response_mode,
                truncated=any(count > 0 for count in omitted_counts.values()),
                omitted_counts=omitted_counts,
                ranking_version=TOPIC_RANKING_VERSION,
                warnings=coalesced_provider_warnings(warnings),
                next_commands=hints,
                provider_status=[],
            ),
        )
        response.meta.response_size_class = json_size_class(response.model_dump(by_alias=True))
        return response

    async def _seed_pmids(
        self,
        request: TopicLiteratureMapRequest,
        warnings: list[ProviderWarning],
    ) -> list[str]:
        seed_pmids: list[str] = []
        if request.pmids:
            seed_pmids.extend(request.pmids)
        if request.query and len(seed_pmids) < request.max_seed_papers:
            try:
                raw = await self.search_client.search_publications(
                    request.query,
                    page=1,
                    sort="score desc",
                )
            except Exception as exc:
                warnings.append(_provider_failed_warning("pubtator_search", exc))
                raw = {"results": []}
            seed_pmids.extend(_pmids_from_search(raw))
        return _dedupe(seed_pmids)[: request.max_seed_papers]

    async def _metadata_papers(
        self,
        pmids: Sequence[str],
        *,
        include_entities: bool,
        warnings: list[ProviderWarning],
    ) -> tuple[dict[str, LiteraturePaper], dict[str, list[LiteratureEntity]]]:
        if not pmids:
            return {}, {}
        try:
            response = await self.metadata_service.get_metadata(
                PublicationMetadataRequest(
                    pmids=list(pmids),
                    include_mesh=include_entities,
                    include_publication_types=True,
                    include_citations="none",
                    include_coverage=True,
                )
            )
        except Exception as exc:
            warnings.append(_provider_failed_warning("pubmed_metadata", exc))
            return {}, {}
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
        warnings: list[ProviderWarning],
    ) -> tuple[list[LiteraturePaper], list[LiteratureGraphEdge], list[str], dict[str, int]]:
        papers: list[LiteraturePaper] = []
        edges: list[LiteratureGraphEdge] = []
        candidate_pmids: list[str] = []
        for seed_pmid in seed_pmids:
            remaining = remaining_neighbors.get(seed_pmid, 0)
            if remaining <= 0:
                continue
            try:
                graph = await self.citation_graph_service.get_citation_graph(
                    PublicationCitationGraphRequest(
                        pmid=seed_pmid,
                        direction="both",
                        max_results=remaining,
                    )
                )
            except Exception as exc:
                warnings.append(_provider_failed_warning("citation_graph", exc))
                continue
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
        return papers, edges, _dedupe(candidate_pmids), remaining_neighbors

    async def _related_candidates(
        self,
        *,
        seed_pmids: list[str],
        request: TopicLiteratureMapRequest,
        remaining_neighbors: dict[str, int],
        warnings: list[ProviderWarning],
    ) -> tuple[list[LiteraturePaper], list[LiteratureGraphEdge], list[str]]:
        papers: list[LiteraturePaper] = []
        edges: list[LiteratureGraphEdge] = []
        candidate_pmids: list[str] = []
        for seed_pmid in seed_pmids:
            remaining = remaining_neighbors.get(seed_pmid, 0)
            if remaining <= 0:
                continue
            try:
                response = await self.related_evidence_service.find_candidates(
                    RelatedEvidenceCandidatesRequest(
                        pmid=seed_pmid,
                        max_results=remaining,
                        prefer_full_text=request.prefer_full_text,
                        include_pubtator_search=True,
                        include_citation_neighbors=False,
                        year_min=request.year_min,
                        year_max=request.year_max,
                    )
                )
            except Exception as exc:
                warnings.append(_provider_failed_warning("related_evidence", exc))
                continue
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
    has_full_text = metadata.coverage == "full_text" or bool(metadata.pmcid)
    return LiteraturePaper(
        pmid=metadata.pmid,
        doi=metadata.doi,
        pmcid=metadata.pmcid,
        title=metadata.title,
        journal=metadata.journal,
        year=metadata.pub_year,
        publication_types=metadata.publication_types,
        authors=[
            LiteratureAuthor(name=author.display_name)
            for author in metadata.authors
            if author.display_name
        ],
        availability=LiteratureAvailability(has_pmc_full_text=has_full_text),
        status="resolved_full_text_candidate" if has_full_text else "resolved_metadata_only",
        provenance=[LiteratureGraphProvenance(provider="pubmed_metadata")],
    )


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
    availability = primary.availability.model_copy(
        update={
            "has_pmc_full_text": (
                primary.availability.has_pmc_full_text or fallback.availability.has_pmc_full_text
            ),
            "is_open_access": primary.availability.is_open_access
            or fallback.availability.is_open_access,
            "has_pdf": primary.availability.has_pdf or fallback.availability.has_pdf,
            "full_text_url": primary.availability.full_text_url
            or fallback.availability.full_text_url,
            "oa_status": primary.availability.oa_status or fallback.availability.oa_status,
            "license_or_access_hint": primary.availability.license_or_access_hint
            or fallback.availability.license_or_access_hint,
        }
    )
    return primary.model_copy(
        update={
            "doi": primary.doi or fallback.doi,
            "pmcid": primary.pmcid or fallback.pmcid,
            "openalex_id": primary.openalex_id or fallback.openalex_id,
            "title": primary.title or fallback.title,
            "journal": primary.journal or fallback.journal,
            "year": primary.year or fallback.year,
            "publication_types": primary.publication_types or fallback.publication_types,
            "authors": primary.authors or fallback.authors,
            "availability": availability,
            "status": _best_status(primary, fallback),
            "provenance": [*primary.provenance, *fallback.provenance],
        }
    )


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


def _best_status(primary: LiteraturePaper, fallback: LiteraturePaper) -> LiteraturePaperStatus:
    if (
        primary.status == "resolved_full_text_candidate"
        or fallback.status == "resolved_full_text_candidate"
    ):
        return "resolved_full_text_candidate"
    if primary.status == "resolved_metadata_only" or fallback.status == "resolved_metadata_only":
        return "resolved_metadata_only"
    if primary.status == "publisher_entitlement_required":
        return primary.status
    return fallback.status


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
) -> TopicLiteratureMapSummary:
    paper_by_key = {paper.key: paper for paper in papers}
    seed_rank = {pmid: index for index, pmid in enumerate(seed_pmids)}
    degree = Counter[str]()
    for edge in edges:
        if edge.edge_type not in {"cites", "cited_by", "related_by_elink"}:
            continue
        degree[edge.source] += 1
        degree[edge.target] += 1

    central_papers = sorted(
        papers,
        key=lambda paper: (
            paper.pmid not in seed_rank,
            -degree[paper.key],
            seed_rank.get(paper.pmid or "", len(seed_rank)),
            -(paper.year or 0),
            paper.pmid or paper.key,
        ),
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
            "arguments": {"pmids": pmids, "prepare_mode": "selected"},
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


def _summary_without_papers(
    summary: TopicLiteratureMapSummary,
    recommended_next_pmids: list[str],
) -> TopicLiteratureMapSummary:
    return TopicLiteratureMapSummary(
        dominant_author_groups=summary.dominant_author_groups,
        recommended_next_pmids=recommended_next_pmids,
    )


def _summary_paper_count(summary: TopicLiteratureMapSummary) -> int:
    return (
        len(summary.central_papers)
        + len(summary.recent_connected_papers)
        + len(summary.bridge_papers)
        + len(summary.accessible_full_text_candidates)
        + len(summary.closed_central_sources)
    )


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


def _provider_failed_warning(provider: str, exc: Exception) -> ProviderWarning:
    return ProviderWarning(
        provider=provider,
        status="provider_failed",
        retryable=True,
        message=str(exc) or exc.__class__.__name__,
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
