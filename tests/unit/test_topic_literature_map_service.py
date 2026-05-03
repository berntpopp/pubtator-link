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
from pubtator_link.services.topic_literature_map import TopicLiteratureMapService


class FakeSearchClient:
    async def search_publications(
        self,
        text: str,
        *,
        page: int = 1,
        sort: str | None = None,
    ) -> dict[str, object]:
        assert text == "FMF"
        assert page == 1
        assert sort == "relevance"
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
