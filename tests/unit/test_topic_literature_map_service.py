from __future__ import annotations

import asyncio

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
    PublicationMetadataRequest,
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


class NoopSearchClient:
    async def search_publications(
        self,
        text: str,
        *,
        page: int = 1,
        sort: str | None = None,
    ) -> dict[str, object]:
        return {"results": []}


class MixedQualitySeedSearchClient:
    async def search_publications(
        self,
        text: str,
        *,
        page: int = 1,
        sort: str | None = None,
    ) -> dict[str, object]:
        assert page == 1
        assert sort == "score desc"
        return {
            "results": [
                {"pmid": "33822308", "score": 100.0},
                {"pmid": "40616106", "score": 90.0},
                {"pmid": "40234174", "score": 80.0},
                {"pmid": "26802180", "score": 70.0},
            ]
        }


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
                title="Familial Mediterranean fever colchicine guideline child paper 333",
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
            "33822308": PublicationMetadata(
                pmid="33822308",
                title="CIS annual meeting selected abstracts",
                journal="Clinical immunology abstracts",
                pub_year=2021,
                publication_types=["Congress", "Abstract"],
            ),
            "40616106": PublicationMetadata(
                pmid="40616106",
                title="Behcet disease and trisomy 8 case report",
                journal="Rheumatology reports",
                pub_year=2025,
                publication_types=["Case Reports"],
            ),
            "40234174": PublicationMetadata(
                pmid="40234174",
                title=(
                    "EULAR/PReS recommendations for the management of familial Mediterranean fever"
                ),
                journal="Annals of the Rheumatic Diseases",
                pub_year=2024,
                publication_types=["Practice Guideline"],
            ),
            "26802180": PublicationMetadata(
                pmid="26802180",
                title="EULAR recommendations for the management of familial Mediterranean fever",
                journal="Annals of the Rheumatic Diseases",
                pub_year=2016,
                publication_types=["Guideline"],
            ),
        }
        pmids = request.pmids
        return PublicationMetadataResponse(
            metadata=[metadata[pmid] for pmid in pmids if pmid in metadata]
        )


class RecordingTopicMetadata:
    def __init__(self) -> None:
        self.requests: list[PublicationMetadataRequest] = []

    async def get_metadata(
        self, request: PublicationMetadataRequest
    ) -> PublicationMetadataResponse:
        self.requests.append(request)
        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid=pmid,
                    title=f"Paper {pmid}",
                    journal="Journal",
                    pub_year=2024,
                    mesh_headings=["Familial Mediterranean Fever"],
                )
                for pmid in request.pmids
            ]
        )


class PartialFailureTopicMetadata:
    def __init__(self) -> None:
        self.requests: list[PublicationMetadataRequest] = []

    async def get_metadata(
        self, request: PublicationMetadataRequest
    ) -> PublicationMetadataResponse:
        self.requests.append(request)
        if len(self.requests) == 2:
            raise RuntimeError("metadata unavailable")
        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid=pmid,
                    title=f"Paper {pmid}",
                    journal="Journal",
                    pub_year=2024,
                    mesh_headings=["Familial Mediterranean Fever"],
                )
                for pmid in request.pmids
            ]
        )


class AllFailedTopicMetadata:
    async def get_metadata(
        self, request: PublicationMetadataRequest
    ) -> PublicationMetadataResponse:
        return PublicationMetadataResponse(
            metadata=[],
            failed_pmids=dict.fromkeys(request.pmids, "metadata unavailable"),
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


class OneFailingCitationGraph:
    async def get_citation_graph(self, request: object) -> PublicationCitationGraphResponse:
        if request.pmid == "222":
            raise RuntimeError("citation provider unavailable")
        return PublicationCitationGraphResponse(
            source=LiteraturePaper(pmid=request.pmid),
            references=[LiteraturePaper(pmid="333", title="Paper 333")],
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


class EmptyCitationGraph:
    async def get_citation_graph(self, request: object) -> PublicationCitationGraphResponse:
        return PublicationCitationGraphResponse(source=LiteraturePaper(pmid=request.pmid))


class OffTopicHighDegreeCitationGraph:
    async def get_citation_graph(self, request: object) -> PublicationCitationGraphResponse:
        if request.pmid == "40616106":
            return PublicationCitationGraphResponse(
                source=LiteraturePaper(pmid=request.pmid),
                references=[
                    LiteraturePaper(pmid=f"90{index}", title=f"Atopy neighbor {index}")
                    for index in range(6)
                ],
                candidate_pmids=[f"90{index}" for index in range(6)],
            )
        return PublicationCitationGraphResponse(
            source=LiteraturePaper(pmid=request.pmid),
            references=[LiteraturePaper(pmid="27679472", title="Discontinuing colchicine")],
            candidate_pmids=["27679472"],
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


class SlowCitationGraph:
    async def get_citation_graph(self, request: object) -> PublicationCitationGraphResponse:
        await asyncio.sleep(0.2)
        return PublicationCitationGraphResponse(
            source=LiteraturePaper(pmid=request.pmid),
            references=[LiteraturePaper(pmid="999", title="Slow reference")],
            candidate_pmids=["999"],
        )


class ConcurrentCitationGraph:
    def __init__(self) -> None:
        self.in_flight = 0
        self.max_in_flight = 0

    async def get_citation_graph(self, request: object) -> PublicationCitationGraphResponse:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        return PublicationCitationGraphResponse(
            source=LiteraturePaper(pmid=request.pmid),
            references=[LiteraturePaper(pmid=f"9{request.pmid}", title="Concurrent reference")],
            candidate_pmids=[f"9{request.pmid}"],
        )


class ConcurrentRelatedEvidence:
    def __init__(self) -> None:
        self.in_flight = 0
        self.max_in_flight = 0

    async def find_candidates(self, request: object) -> RelatedEvidenceCandidatesResponse:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        return RelatedEvidenceCandidatesResponse(
            source=LiteraturePaper(pmid=request.pmid),
            candidates=[
                RelatedEvidenceCandidate(
                    paper=LiteraturePaper(pmid=f"8{request.pmid}", title="Concurrent related"),
                    score=1.0,
                    match_reasons=["pubmed_neighbor_score"],
                )
            ],
            candidate_pmids=[f"8{request.pmid}"],
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
    assert paper_333.title == "Familial Mediterranean fever colchicine guideline child paper 333"
    assert paper_333.authors[0].name == "Bea"


@pytest.mark.asyncio
async def test_topic_metadata_papers_batches_more_than_public_cap() -> None:
    metadata = RecordingTopicMetadata()
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=metadata,
        citation_graph_service=FakeCitationGraph(),
        related_evidence_service=FakeRelatedEvidence(),
    )
    pmids = [str(pmid) for pmid in range(300000, 300105)]
    warnings = []

    papers, entities = await service._metadata_papers(
        pmids,
        include_entities=True,
        warnings=warnings,
    )

    assert [len(request.pmids) for request in metadata.requests] == [100, 5]
    assert [
        (
            request.include_mesh,
            request.include_publication_types,
            request.include_citations,
            request.include_coverage,
        )
        for request in metadata.requests
    ] == [(True, True, "none", True), (True, True, "none", True)]
    assert set(papers) == set(pmids)
    assert set(entities) == set(pmids)
    assert warnings == []


@pytest.mark.asyncio
async def test_topic_metadata_papers_preserves_mesh_option_when_entities_disabled() -> None:
    metadata = RecordingTopicMetadata()
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=metadata,
        citation_graph_service=FakeCitationGraph(),
        related_evidence_service=FakeRelatedEvidence(),
    )
    warnings = []

    papers, entities = await service._metadata_papers(
        ["310000"],
        include_entities=False,
        warnings=warnings,
    )

    assert set(papers) == {"310000"}
    assert entities == {}
    assert metadata.requests[0].include_mesh is False
    assert metadata.requests[0].include_publication_types is True
    assert metadata.requests[0].include_citations == "none"
    assert metadata.requests[0].include_coverage is True
    assert warnings == []


@pytest.mark.asyncio
async def test_topic_metadata_papers_partial_batch_failure_preserves_successful_metadata() -> None:
    metadata = PartialFailureTopicMetadata()
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=metadata,
        citation_graph_service=FakeCitationGraph(),
        related_evidence_service=FakeRelatedEvidence(),
    )
    pmids = [str(pmid) for pmid in range(400000, 400105)]
    warnings = []

    papers, entities = await service._metadata_papers(
        pmids,
        include_entities=True,
        warnings=warnings,
    )

    assert [len(request.pmids) for request in metadata.requests] == [100, 5]
    assert set(papers) == set(pmids[:100])
    assert set(entities) == set(pmids[:100])
    assert any(
        warning.provider == "pubmed_metadata"
        and warning.status == "provider_failed"
        and warning.retryable is True
        for warning in warnings
    )


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


@pytest.mark.asyncio
async def test_build_map_records_provider_status_for_completed_stages() -> None:
    response = await _service().build_map(
        TopicLiteratureMapRequest(
            query="FMF",
            max_seed_papers=1,
            max_neighbors_per_paper=2,
        )
    )

    statuses = {(status.provider, status.operation): status for status in response.provider_status}

    assert statuses[("pubtator_search", "seed_search")].status == "success"
    assert statuses[("pubmed_metadata", "seed_metadata")].status == "success"
    assert statuses[("citation_graph", "neighbor_enrichment")].status == "success"
    assert statuses[("related_evidence", "candidate_enrichment")].status == "success"
    assert response.meta.provider_status == response.provider_status


@pytest.mark.asyncio
async def test_build_map_aggregates_citation_provider_status_across_seeds() -> None:
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=FakeMetadata(),
        citation_graph_service=OneFailingCitationGraph(),
        related_evidence_service=EmptyRelatedEvidence(),
    )

    response = await service.build_map(
        TopicLiteratureMapRequest(
            pmids=["111", "222"],
            max_seed_papers=2,
            max_neighbors_per_paper=1,
            include_related_candidates=False,
        )
    )

    citation_statuses = [
        status
        for status in response.provider_status
        if status.provider == "citation_graph" and status.operation == "neighbor_enrichment"
    ]
    assert len(citation_statuses) == 1
    assert citation_statuses[0].status == "partial"
    assert citation_statuses[0].result_count == 1
    assert citation_statuses[0].retryable is True
    assert citation_statuses[0].message is not None
    assert "failed_seed_pmids=1" in citation_statuses[0].message


@pytest.mark.asyncio
async def test_build_map_returns_partial_response_when_citation_stage_times_out() -> None:
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=FakeMetadata(),
        citation_graph_service=SlowCitationGraph(),
        related_evidence_service=EmptyRelatedEvidence(),
    )

    response = await service.build_map(
        TopicLiteratureMapRequest(
            pmids=["111"],
            max_seed_papers=1,
            max_neighbors_per_paper=1,
            timeout_ms=50,
        )
    )

    assert response.seed_pmids == ["111"]
    assert any(node.paper is not None and node.paper.pmid == "111" for node in response.nodes)
    assert not any(edge.edge_type in {"cites", "cited_by"} for edge in response.edges)
    assert any(
        warning.provider == "citation_graph"
        and warning.retryable is True
        and "timed out" in warning.message
        for warning in response.meta.warnings
    )
    citation_status = next(
        status
        for status in response.provider_status
        if status.provider == "citation_graph" and status.operation == "neighbor_enrichment"
    )
    assert citation_status.status == "failed"
    assert citation_status.retryable is True
    assert citation_status.message is not None
    assert "timed out" in citation_status.message
    assert any(
        command["tool"] == "pubtator.build_topic_literature_map"
        and command["arguments"]["include_citations"] is False
        and command["arguments"]["timeout_ms"] == 50
        for command in response.meta.next_commands
    )
    related_status = next(
        status
        for status in response.provider_status
        if status.provider == "related_evidence" and status.operation == "candidate_enrichment"
    )
    assert related_status.status == "skipped"
    assert related_status.retryable is False


@pytest.mark.asyncio
async def test_topic_map_stage_budgets_prevent_citation_timeout_from_starving_related() -> None:
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=FakeMetadata(),
        citation_graph_service=SlowCitationGraph(),
        related_evidence_service=FakeRelatedEvidence(),
    )

    response = await service.build_map(
        TopicLiteratureMapRequest(
            pmids=["111"],
            max_seed_papers=1,
            max_neighbors_per_paper=2,
            timeout_ms=500,
            citation_graph_timeout_ms=50,
            related_evidence_timeout_ms=300,
        )
    )

    citation_status = next(
        status
        for status in response.provider_status
        if status.provider == "citation_graph" and status.operation == "neighbor_enrichment"
    )
    related_status = next(
        status
        for status in response.provider_status
        if status.provider == "related_evidence" and status.operation == "candidate_enrichment"
    )
    assert citation_status.status == "failed"
    assert related_status.status == "success"
    assert response.top_candidates
    assert response.top_candidates[0].pmid == "333"


@pytest.mark.asyncio
async def test_topic_map_parallelizes_seed_network_enrichment() -> None:
    citation_graph = ConcurrentCitationGraph()
    related_evidence = ConcurrentRelatedEvidence()
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=FakeMetadata(),
        citation_graph_service=citation_graph,
        related_evidence_service=related_evidence,
    )

    response = await service.build_map(
        TopicLiteratureMapRequest(
            pmids=["111", "222", "333"],
            max_seed_papers=3,
            max_neighbors_per_paper=2,
        )
    )

    assert citation_graph.max_in_flight > 1
    assert related_evidence.max_in_flight > 1
    assert response.top_candidates


@pytest.mark.asyncio
async def test_topic_map_exposes_bias_scores_and_recent_definition() -> None:
    response = await _service().build_map(
        TopicLiteratureMapRequest(
            query="FMF colchicine guideline child",
            max_seed_papers=2,
            max_neighbors_per_paper=2,
            bias_toward=["guideline", "pediatric"],
        )
    )

    assert response.bias_score_by_pmid
    assert response.summary.recent_connected_definition
    assert "months" in response.summary.recent_connected_definition


@pytest.mark.asyncio
async def test_build_map_records_metadata_failure_status_when_all_pmids_fail() -> None:
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=AllFailedTopicMetadata(),
        citation_graph_service=EmptyCitationGraph(),
        related_evidence_service=EmptyRelatedEvidence(),
    )

    response = await service.build_map(
        TopicLiteratureMapRequest(
            pmids=["111"],
            include_citations=False,
            include_related_candidates=False,
        )
    )

    metadata_status = next(
        status
        for status in response.provider_status
        if status.provider == "pubmed_metadata" and status.operation == "seed_metadata"
    )
    assert metadata_status.status == "failed"
    assert metadata_status.retryable is True


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
    compact_central_by_pmid = {
        paper.pmid: paper for paper in response.summary.central_papers if paper.pmid
    }
    assert compact_central_by_pmid["111"].authors == []
    assert compact_central_by_pmid["111"].author_summary == "Ada"
    assert compact_central_by_pmid["111"].author_count == 1
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
async def test_topic_map_filters_weak_query_seeds_before_neighbor_expansion() -> None:
    service = TopicLiteratureMapService(
        search_client=MixedQualitySeedSearchClient(),
        metadata_service=FakeMetadata(),
        citation_graph_service=EmptyCitationGraph(),
        related_evidence_service=EmptyRelatedEvidence(),
    )

    response = await service.build_map(
        TopicLiteratureMapRequest(
            query="colchicine pediatric familial Mediterranean fever MEFV variants guideline",
            max_seed_papers=2,
            include_citations=False,
            include_related_candidates=False,
            bias_toward=["guideline", "pediatric", "genotype_phenotype"],
        )
    )

    assert response.seed_pmids == ["40234174", "26802180"]
    assert "33822308" not in response.seed_pmids
    assert "40616106" not in response.seed_pmids


@pytest.mark.asyncio
async def test_topic_map_central_papers_prefer_query_relevance_over_neighbor_degree() -> None:
    service = TopicLiteratureMapService(
        search_client=NoopSearchClient(),
        metadata_service=FakeMetadata(),
        citation_graph_service=OffTopicHighDegreeCitationGraph(),
        related_evidence_service=EmptyRelatedEvidence(),
    )

    response = await service.build_map(
        TopicLiteratureMapRequest(
            query="familial Mediterranean fever colchicine guideline",
            pmids=["40616106", "40234174"],
            max_neighbors_per_paper=6,
            include_related_candidates=False,
            bias_toward=["guideline"],
        )
    )

    assert response.summary.central_papers[0].pmid == "40234174"


@pytest.mark.asyncio
async def test_topic_map_compact_exposes_recommendation_summaries_and_graph_hint() -> None:
    response = await _service().build_map(
        TopicLiteratureMapRequest(
            query="FMF colchicine guideline child",
            max_seed_papers=2,
            max_neighbors_per_paper=2,
            response_mode="compact",
            max_candidates=3,
            max_demoted=20,
        )
    )

    assert response.summary.accessible_full_text_candidates
    assert response.recommended_next_candidates
    assert response.recommended_next_candidates[0].pmid in response.recommended_next_pmids
    assert response.recommended_next_candidates[0].title
    assert response.graph_inspection_hint
    assert all(not candidate.demotion_reasons for candidate in response.top_candidates)


@pytest.mark.asyncio
async def test_topic_map_demoted_candidate_pmids_exclude_seed_pmids() -> None:
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=FakeMetadata(),
        citation_graph_service=WideCitationGraph(),
        related_evidence_service=EmptyRelatedEvidence(),
    )

    response = await service.build_map(
        TopicLiteratureMapRequest(
            query="FMF colchicine guideline child",
            max_seed_papers=2,
            max_neighbors_per_paper=2,
            max_demoted=20,
        )
    )

    assert response.demoted_candidate_pmids
    assert set(response.demoted_candidate_pmids).isdisjoint(response.seed_pmids)
