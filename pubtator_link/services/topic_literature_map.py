"""Topic-level literature map orchestration service."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any, Protocol

from pubtator_link.models.literature_graph import (
    LiteratureAuthor,
    LiteratureAvailability,
    LiteratureEntity,
    LiteratureGraphEdge,
    LiteratureGraphNode,
    LiteratureGraphProvenance,
    LiteraturePaper,
    LiteraturePaperStatus,
    LiteratureResponseMeta,
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
        hints = _retrieval_hints(summary.recommended_next_pmids)

        return TopicLiteratureMapResponse(
            query=request.query,
            seed_pmids=seed_pmids,
            summary=summary,
            nodes=nodes,
            edges=deduped_edges,
            candidate_retrieval_hints=hints,
            _meta=LiteratureResponseMeta(warnings=warnings, next_commands=hints),
        )

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
                    sort="relevance",
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
