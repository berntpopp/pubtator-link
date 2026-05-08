from __future__ import annotations

import pytest

from pubtator_link.models.literature_graph import (
    LiteratureAvailability,
    LiteraturePaper,
    PublicationCitationGraphResponse,
    RelatedEvidenceCandidate,
    RelatedEvidenceCandidatesResponse,
    TopicLiteratureMapRequest,
)
from pubtator_link.models.publication_metadata import (
    PublicationAuthor,
    PublicationMetadata,
    PublicationMetadataResponse,
)
from pubtator_link.services.literature_graph_compact import TOPIC_RANKING_VERSION
from pubtator_link.services.topic_literature_map import (
    TopicLiteratureMapService,
    rank_topic_candidates,
)


def assert_no_prepare_mode(payload: object) -> None:
    assert "prepare_mode" not in str(payload)


def _summary_paper_count(summary: object) -> int:
    return sum(
        len(getattr(summary, field))
        for field in (
            "central_papers",
            "recent_connected_papers",
            "bridge_papers",
            "accessible_full_text_candidates",
            "closed_central_sources",
        )
    )


class FakeSearchClient:
    async def search_publications(
        self,
        text: str,
        *,
        page: int = 1,
        sort: str | None = None,
    ) -> dict[str, object]:
        assert "FMF" in text
        assert page == 1
        assert sort == "score desc"
        return {"results": [{"pmid": "111"}, {"pmid": "222"}]}


class FakeMetadata:
    async def get_metadata(self, request: object) -> PublicationMetadataResponse:
        metadata = {
            "111": PublicationMetadata(
                pmid="111",
                title="Paper 111",
                journal="Journal A",
                pub_year=2024,
                pmcid="PMC111",
                authors=[PublicationAuthor(fore_name="Ada")],
                mesh_headings=["Familial Mediterranean Fever"],
                coverage="full_text",
            ),
            "222": PublicationMetadata(
                pmid="222",
                title="Paper 222",
                journal="Journal B",
                pub_year=2023,
                authors=[PublicationAuthor(fore_name="Ada")],
            ),
            "333": PublicationMetadata(
                pmid="333",
                title="Paper 333",
                journal="Journal C",
                pub_year=2022,
                pmcid="PMC333",
                authors=[PublicationAuthor(fore_name="Bea")],
                coverage="full_text",
            ),
            "444": PublicationMetadata(
                pmid="444",
                title="Metadata only title",
            ),
        }
        pmids = request.pmids
        return PublicationMetadataResponse(
            metadata=[metadata[pmid] for pmid in pmids if pmid in metadata]
        )


class FakeCitationGraph:
    async def get_citation_graph(self, request: object) -> PublicationCitationGraphResponse:
        pmid = request.pmid
        return PublicationCitationGraphResponse(
            source=LiteraturePaper(pmid=pmid),
            references=[LiteraturePaper(pmid="333", title="Paper 333")],
            candidate_pmids=["333"],
        )


class FakeRelatedEvidence:
    async def find_candidates(self, request: object) -> RelatedEvidenceCandidatesResponse:
        pmid = request.pmid
        return RelatedEvidenceCandidatesResponse(
            source=LiteraturePaper(pmid=pmid),
            candidates=[
                RelatedEvidenceCandidate(
                    paper=LiteraturePaper(
                        pmid="333",
                        title="Paper 333",
                        availability=LiteratureAvailability(has_pmc_full_text=True),
                    ),
                    score=800,
                    match_reasons=["pubmed_neighbor_score"],
                    pubmed_neighbor_score=800,
                )
            ],
            candidate_pmids=["333"],
        )


class WideCitationGraph:
    async def get_citation_graph(self, request: object) -> PublicationCitationGraphResponse:
        return PublicationCitationGraphResponse(
            source=LiteraturePaper(pmid=request.pmid),
            references=[
                LiteraturePaper(pmid="333", title="Sparse citation"),
                LiteraturePaper(pmid="444", title="Extra reference"),
            ],
            cited_by=[LiteraturePaper(pmid="555", title="Extra citing")],
            candidate_pmids=["333", "444", "555"],
        )


class WideRelatedEvidence:
    async def find_candidates(self, request: object) -> RelatedEvidenceCandidatesResponse:
        return RelatedEvidenceCandidatesResponse(
            source=LiteraturePaper(pmid=request.pmid),
            candidates=[
                RelatedEvidenceCandidate(
                    paper=LiteraturePaper(pmid="666", title="Extra related"),
                    score=500,
                    match_reasons=["pubmed_neighbor_score"],
                    pubmed_neighbor_score=500,
                )
            ],
            candidate_pmids=["666"],
        )


class RichNeighborCitationGraph:
    async def get_citation_graph(self, request: object) -> PublicationCitationGraphResponse:
        return PublicationCitationGraphResponse(
            source=LiteraturePaper(pmid=request.pmid),
            references=[
                LiteraturePaper(
                    pmid="444",
                    title="Rich citation title",
                    year=2021,
                    availability=LiteratureAvailability(has_pmc_full_text=True),
                )
            ],
            candidate_pmids=["444"],
        )


class DoiOnlyCitationGraph:
    async def get_citation_graph(self, request: object) -> PublicationCitationGraphResponse:
        return PublicationCitationGraphResponse(
            source=LiteraturePaper(pmid=request.pmid),
            references=[
                LiteraturePaper(
                    doi="10.1000/unresolved-topic",
                    title="FMF unresolved DOI-only reference",
                )
            ],
            candidate_pmids=[],
        )


class EmptyRelatedEvidence:
    async def find_candidates(self, request: object) -> RelatedEvidenceCandidatesResponse:
        return RelatedEvidenceCandidatesResponse(
            source=LiteraturePaper(pmid=request.pmid),
            candidates=[],
            candidate_pmids=[],
        )


class FailingProvider:
    async def get_metadata(self, request: object) -> PublicationMetadataResponse:
        raise RuntimeError("metadata unavailable")

    async def get_citation_graph(self, request: object) -> PublicationCitationGraphResponse:
        raise RuntimeError("citation unavailable")

    async def find_candidates(self, request: object) -> RelatedEvidenceCandidatesResponse:
        raise RuntimeError("related unavailable")


def _service() -> TopicLiteratureMapService:
    return TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=FakeMetadata(),
        citation_graph_service=FakeCitationGraph(),
        related_evidence_service=FakeRelatedEvidence(),
    )


@pytest.mark.asyncio
async def test_build_map_from_query_returns_seed_author_edges_and_hints() -> None:
    response = await _service().build_map(
        TopicLiteratureMapRequest(
            query="FMF",
            max_seed_papers=2,
            max_neighbors_per_paper=2,
        )
    )

    assert response.seed_pmids == ["111", "222"]
    assert {node.node_type for node in response.nodes} >= {"paper", "author"}
    assert {edge.edge_type for edge in response.edges} >= {
        "authored_by",
        "cites",
        "related_by_elink",
    }
    assert response.summary.central_papers[0].pmid == "111"
    assert response.summary.recommended_next_pmids
    assert response.candidate_retrieval_hints[0]["tool"] == "pubtator.get_publication_passages"
    assert "entity" in {node.node_type for node in response.nodes}
    assert "mentions_entity" in {edge.edge_type for edge in response.edges}


@pytest.mark.asyncio
async def test_build_map_bounds_explicit_seeds_and_neighbors() -> None:
    response = await _service().build_map(
        TopicLiteratureMapRequest(
            pmids=["111", "222", "333"],
            max_seed_papers=1,
            max_neighbors_per_paper=1,
        )
    )

    assert response.seed_pmids == ["111"]
    neighbor_edges = [
        edge
        for edge in response.edges
        if edge.edge_type in {"cites", "cited_by", "related_by_elink"}
    ]
    assert len(neighbor_edges) <= 1


@pytest.mark.asyncio
async def test_build_map_enforces_total_neighbor_bound_and_prefers_metadata() -> None:
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=FakeMetadata(),
        citation_graph_service=WideCitationGraph(),
        related_evidence_service=WideRelatedEvidence(),
    )

    response = await service.build_map(
        TopicLiteratureMapRequest(
            pmids=["111"],
            max_seed_papers=1,
            max_neighbors_per_paper=1,
        )
    )

    neighbor_edges = [
        edge
        for edge in response.edges
        if edge.edge_type in {"cites", "cited_by", "related_by_elink"}
    ]
    paper_333 = next(
        node.paper for node in response.nodes if node.paper is not None and node.paper.pmid == "333"
    )

    assert len(neighbor_edges) == 1
    assert paper_333.title == "Paper 333"
    assert paper_333.authors[0].name == "Bea"


@pytest.mark.asyncio
async def test_build_map_does_not_overwrite_richer_neighbor_with_sparse_metadata() -> None:
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=FakeMetadata(),
        citation_graph_service=RichNeighborCitationGraph(),
        related_evidence_service=WideRelatedEvidence(),
    )

    response = await service.build_map(
        TopicLiteratureMapRequest(
            pmids=["111"],
            max_seed_papers=1,
            max_neighbors_per_paper=1,
        )
    )

    paper_444 = next(
        node.paper for node in response.nodes if node.paper is not None and node.paper.pmid == "444"
    )

    assert paper_444.title == "Rich citation title"
    assert paper_444.year == 2021
    assert paper_444.availability.has_pmc_full_text is True


@pytest.mark.asyncio
async def test_build_map_degrades_with_provider_warnings() -> None:
    provider = FailingProvider()
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=provider,
        citation_graph_service=provider,
        related_evidence_service=provider,
    )

    response = await service.build_map(
        TopicLiteratureMapRequest(
            pmids=["111"],
            max_seed_papers=1,
            max_neighbors_per_paper=1,
        )
    )

    assert response.seed_pmids == ["111"]
    assert [node.paper.pmid for node in response.nodes if node.paper is not None] == ["111"]
    assert {warning.provider for warning in response.meta.warnings} == {
        "pubmed_metadata",
        "citation_graph",
        "related_evidence",
    }


def test_topic_ranker_promotes_guideline_and_pediatric_colchicine_records() -> None:
    papers = [
        LiteraturePaper(
            pmid="33778981",
            title="Veterinary clinical pathology annual meeting abstracts",
            publication_types=["Congress"],
        ),
        LiteraturePaper(
            pmid="40616106",
            title="Behcet disease and trisomy 8 case report",
            publication_types=["Case Reports"],
        ),
        LiteraturePaper(
            pmid="28386255",
            title="EULAR recommendations for the management of familial Mediterranean fever",
            publication_types=["Guideline"],
            year=2016,
        ),
        LiteraturePaper(
            pmid="36680425",
            title=(
                "PREDICT-crFMF score in children with colchicine-resistant familial "
                "Mediterranean fever"
            ),
            publication_types=["Journal Article"],
            year=2023,
        ),
    ]

    ranked = rank_topic_candidates(
        papers,
        query="familial Mediterranean fever MEFV colchicine guideline Turkey child variant",
        seed_pmids=[],
        candidate_pmids=[paper.pmid for paper in papers if paper.pmid],
        accessible_pmids=[],
        bias_toward=["guideline", "pediatric"],
    )

    by_pmid = {candidate.pmid: candidate for candidate in ranked}
    assert [candidate.pmid for candidate in ranked[:3]] == ["28386255", "36680425", "33778981"]
    assert "conference_abstract_collection" in by_pmid["33778981"].demotion_reasons
    assert "low_query_overlap" in by_pmid["40616106"].demotion_reasons
    assert by_pmid["28386255"].relevance_to_query is not None
    assert "guideline_intent" in by_pmid["28386255"].relevance_to_query.matched_intents


@pytest.mark.asyncio
async def test_topic_map_compact_keeps_summary_papers_and_candidate_signals() -> None:
    response = await _service().build_map(
        TopicLiteratureMapRequest(
            query="FMF colchicine guideline child",
            max_seed_papers=2,
            max_neighbors_per_paper=2,
            response_mode="compact",
            max_candidates=3,
            max_demoted=1,
        )
    )

    assert response.meta.response_mode == "compact"
    assert response.nodes == []
    assert response.edges == []
    assert response.summary.central_papers
    assert response.summary.recent_connected_papers
    assert response.summary.bridge_papers
    assert len(response.summary.central_papers) <= 5
    assert len(response.summary.recent_connected_papers) <= 5
    assert len(response.summary.bridge_papers) <= 5
    assert response.summary.central_papers[0].authors == []
    assert response.summary.central_papers[0].author_summary == "Ada"
    assert response.summary.central_papers[0].author_count == 1
    assert response.top_candidates
    assert response.top_candidates[0].signals
    assert len(response.top_candidates[0].signals) == len(set(response.top_candidates[0].signals))
    assert_no_prepare_mode(response.candidate_retrieval_hints)


@pytest.mark.asyncio
async def test_topic_map_compact_serialization_omits_empty_nodes_edges() -> None:
    response = await _service().build_map(
        TopicLiteratureMapRequest(query="FMF", response_mode="compact")
    )

    payload = response.model_dump(by_alias=True)

    assert "nodes" not in payload
    assert "edges" not in payload
    assert response.meta.omitted_counts["nodes"] > 0
    assert response.meta.omitted_counts["edges"] > 0
    assert response.meta.request_signature is not None
    assert response.meta.cache_key == response.meta.request_signature
    assert any(
        command["arguments"]["response_mode"] == "full" for command in response.meta.next_commands
    )


@pytest.mark.asyncio
async def test_topic_map_compact_omitted_summary_papers_count_only_hidden_papers() -> None:
    request_args = {
        "query": "FMF colchicine guideline child",
        "max_seed_papers": 2,
        "max_neighbors_per_paper": 2,
        "max_candidates": 3,
        "max_demoted": 1,
    }

    full_response = await _service().build_map(
        TopicLiteratureMapRequest(**request_args, response_mode="full")
    )
    compact_response = await _service().build_map(
        TopicLiteratureMapRequest(**request_args, response_mode="compact")
    )

    assert compact_response.meta.omitted_counts["summary_papers"] == max(
        0,
        _summary_paper_count(full_response.summary)
        - _summary_paper_count(compact_response.summary),
    )


@pytest.mark.asyncio
async def test_topic_map_compact_hides_doi_only_top_candidates() -> None:
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=FakeMetadata(),
        citation_graph_service=DoiOnlyCitationGraph(),
        related_evidence_service=EmptyRelatedEvidence(),
    )

    response = await service.build_map(
        TopicLiteratureMapRequest(
            pmids=["111"],
            response_mode="compact",
            max_neighbors_per_paper=1,
            max_candidates=5,
        )
    )

    assert all(candidate.pmid for candidate in response.top_candidates)
    assert response.omitted_counts["doi_only_unresolved"] == 1
    assert response.meta.omitted_counts["doi_only_unresolved"] == 1


@pytest.mark.asyncio
async def test_topic_map_compact_filters_doi_only_summary_papers() -> None:
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=FakeMetadata(),
        citation_graph_service=DoiOnlyCitationGraph(),
        related_evidence_service=EmptyRelatedEvidence(),
    )

    response = await service.build_map(
        TopicLiteratureMapRequest(
            pmids=["111"],
            response_mode="compact",
            max_neighbors_per_paper=1,
        )
    )

    summary_payload = response.summary.model_dump(mode="json")
    assert "10.1000/unresolved-topic" not in str(summary_payload)
    assert response.meta.omitted_counts["doi_only_unresolved"] == 1


@pytest.mark.asyncio
async def test_topic_map_nodes_edges_mode_returns_bounded_topology_without_candidate_envelopes() -> (
    None
):
    response = await _service().build_map(
        TopicLiteratureMapRequest(
            pmids=["111", "222"],
            response_mode="nodes_edges",
            max_graph_nodes=2,
            max_graph_edges=1,
        )
    )

    assert response.meta.response_mode == "nodes_edges"
    assert len(response.nodes) <= 2
    assert len(response.edges) <= 1
    assert response.top_candidates == []
    assert response.summary.central_papers == []
    assert response.summary.recent_connected_papers == []
    assert response.summary.bridge_papers == []
    assert response.summary.accessible_full_text_candidates == []
    assert response.summary.closed_central_sources == []


@pytest.mark.asyncio
async def test_topic_map_full_mode_adds_bounded_candidates_and_preserves_topology() -> None:
    response = await _service().build_map(
        TopicLiteratureMapRequest(
            query="FMF",
            max_seed_papers=2,
            max_neighbors_per_paper=2,
            max_candidates=1,
        )
    )

    assert response.meta.response_mode == "full"
    assert response.meta.ranking_version == TOPIC_RANKING_VERSION
    assert 0 < len(response.top_candidates) <= 1
    assert response.nodes
    assert response.edges
    assert response.summary.central_papers


@pytest.mark.asyncio
async def test_topic_map_demoted_candidate_pmids_exclude_seed_pmids() -> None:
    response = await _service().build_map(
        TopicLiteratureMapRequest(
            query="FMF colchicine guideline child",
            max_seed_papers=2,
            max_neighbors_per_paper=2,
            response_mode="compact",
            max_demoted=20,
        )
    )

    assert response.demoted_candidate_pmids
    assert set(response.demoted_candidate_pmids).isdisjoint(response.seed_pmids)
