from __future__ import annotations

import pytest

from pubtator_link.models.discovery import RelatedArticleScoreRecord
from pubtator_link.models.literature_graph import (
    LiteraturePaper,
    LiteratureResponseMeta,
    ProviderWarning,
    PublicationCitationGraphResponse,
    RelatedEvidenceCandidatesRequest,
)
from pubtator_link.models.publication_metadata import (
    PublicationMetadata,
    PublicationMetadataResponse,
)
from pubtator_link.services.related_evidence import RelatedEvidenceService


class FakeDiscovery:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def find_related_article_scores(
        self,
        pmids: list[str],
        limit: int,
    ) -> list[RelatedArticleScoreRecord]:
        assert pmids == ["123"]
        assert 25 <= limit <= 100
        if self.fail:
            raise RuntimeError("ELink unavailable")
        return [
            RelatedArticleScoreRecord(
                source_pmid="123",
                pmid="111",
                neighbor_score=900,
            ),
            RelatedArticleScoreRecord(
                source_pmid="123",
                pmid="222",
                neighbor_score=900,
            ),
        ]


class FilterWindowDiscovery:
    async def find_related_article_scores(
        self,
        pmids: list[str],
        limit: int,
    ) -> list[RelatedArticleScoreRecord]:
        assert pmids == ["123"]
        assert limit > 1
        return [
            RelatedArticleScoreRecord(source_pmid="123", pmid="333", neighbor_score=950),
            RelatedArticleScoreRecord(source_pmid="123", pmid="111", neighbor_score=900),
        ]


class FakeMetadata:
    async def get_metadata(self, request):
        assert request.pmids
        records = {
            "111": PublicationMetadata(
                pmid="111",
                title="Review paper",
                pub_year=2024,
                publication_types=["Review"],
                coverage="abstract_only",
            ),
            "222": PublicationMetadata(
                pmid="222",
                title="Full text paper",
                pub_year=2023,
                publication_types=["Journal Article"],
                coverage="full_text",
            ),
            "333": PublicationMetadata(
                pmid="333",
                title="Citation neighbor",
                pub_year=2022,
                publication_types=["Journal Article"],
                coverage="abstract_only",
            ),
        }
        return PublicationMetadataResponse(
            metadata=[records[pmid] for pmid in request.pmids if pmid in records],
        )


class FailingMetadata:
    async def get_metadata(self, request):
        raise RuntimeError("metadata unavailable")


class FakeCitationGraph:
    async def get_citation_graph(self, request):
        assert request.pmid == "123"
        return PublicationCitationGraphResponse(
            source=LiteraturePaper(pmid="123"),
            candidate_pmids=["333"],
            _meta=LiteratureResponseMeta(
                warnings=[
                    ProviderWarning(
                        provider="citation_fixture",
                        status="partial",
                        message="partial citation graph",
                    )
                ]
            ),
        )


class CitationGraphWithReviewCandidate:
    async def get_citation_graph(self, request):
        return PublicationCitationGraphResponse(
            source=LiteraturePaper(pmid=request.pmid),
            candidate_pmids=["333", "111"],
        )


class IntentDiscovery:
    async def find_related_article_scores(
        self,
        pmids: list[str],
        limit: int,
    ) -> list[RelatedArticleScoreRecord]:
        assert pmids == ["1"]
        assert 25 <= limit <= 100
        return [
            RelatedArticleScoreRecord(
                source_pmid="1",
                pmid="444",
                neighbor_score=900,
            )
        ]


class IntentMetadata:
    async def get_metadata(self, request):
        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid=pmid,
                    title="Pediatric colchicine resistance in familial Mediterranean fever",
                    pub_year=2024,
                    publication_types=["Guideline"],
                    coverage="full_text",
                    pmcid="PMC1",
                )
                for pmid in request.pmids
            ],
        )


class IntentCitationGraph:
    async def get_citation_graph(self, request):
        assert request.pmid == "1"
        return PublicationCitationGraphResponse(
            source=LiteraturePaper(pmid=request.pmid),
            candidate_pmids=[],
        )


@pytest.mark.asyncio
async def test_ranks_full_text_candidate_when_neighbor_scores_tie() -> None:
    service = RelatedEvidenceService(
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
        citation_graph_service=FakeCitationGraph(),
    )

    response = await service.find_candidates(RelatedEvidenceCandidatesRequest(pmid="123"))

    assert response.candidate_pmids[:2] == ["222", "111"]
    assert response.candidates[0].paper.pmid == "222"
    assert response.candidates[0].score == 900
    assert response.candidates[0].pubmed_neighbor_score == 900
    assert "full_text_available" in response.candidates[0].match_reasons


@pytest.mark.asyncio
async def test_filters_publication_type_and_year_without_citation_neighbors() -> None:
    service = RelatedEvidenceService(
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
        citation_graph_service=FakeCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="123",
            publication_types=["Review"],
            year_min=2024,
            include_citation_neighbors=False,
        )
    )

    assert response.candidate_pmids == ["111"]
    assert response.candidates[0].match_reasons == [
        "pubmed_neighbor_score",
        "shared_publication_type",
        "requested_publication_type",
        "year_window_match",
    ]
    assert response.candidates[0].paper.provenance[0].provider == "pubmed_metadata"


@pytest.mark.asyncio
async def test_elink_candidates_do_not_depend_on_pubtator_search_flag() -> None:
    service = RelatedEvidenceService(
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
        citation_graph_service=FakeCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="123",
            include_pubtator_search=False,
            include_citation_neighbors=False,
        )
    )

    assert response.candidate_pmids == ["222", "111"]
    assert response.candidates[0].paper.provenance[0].provider == "pubmed_metadata"
    assert "pubmed_neighbor_score" in response.candidates[0].match_reasons


@pytest.mark.asyncio
async def test_reports_elink_failure_warning_while_returning_citation_graph_candidates() -> None:
    service = RelatedEvidenceService(
        discovery_service=FakeDiscovery(fail=True),
        metadata_service=FakeMetadata(),
        citation_graph_service=FakeCitationGraph(),
    )

    response = await service.find_candidates(RelatedEvidenceCandidatesRequest(pmid="123"))

    assert response.candidate_pmids == ["333"]
    assert any(
        warning.provider == "ncbi_elink" and warning.status == "provider_failed"
        for warning in response.meta.warnings
    )
    assert any(warning.provider == "citation_fixture" for warning in response.meta.warnings)


@pytest.mark.asyncio
async def test_filters_and_ranks_before_applying_final_limit() -> None:
    service = RelatedEvidenceService(
        discovery_service=FilterWindowDiscovery(),
        metadata_service=FakeMetadata(),
        citation_graph_service=CitationGraphWithReviewCandidate(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="123",
            max_results=1,
            publication_types=["Review"],
            include_citation_neighbors=False,
        )
    )

    assert response.candidate_pmids == ["111"]
    assert not response.meta.warnings


@pytest.mark.asyncio
async def test_metadata_failure_degrades_to_bare_candidates_with_warning() -> None:
    service = RelatedEvidenceService(
        discovery_service=FakeDiscovery(),
        metadata_service=FailingMetadata(),
        citation_graph_service=FakeCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(pmid="123", include_citation_neighbors=False)
    )

    assert response.candidate_pmids == ["111", "222"]
    assert response.candidates[0].paper.status == "unresolved_reference"
    assert any(
        warning.provider == "pubmed_metadata" and warning.status == "provider_failed"
        for warning in response.meta.warnings
    )


@pytest.mark.asyncio
async def test_related_evidence_enriches_match_reasons_for_intents_and_access() -> None:
    service = RelatedEvidenceService(
        discovery_service=IntentDiscovery(),
        metadata_service=IntentMetadata(),
        citation_graph_service=IntentCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="1",
            max_results=5,
            publication_types=["Guideline"],
            response_mode="compact",
        )
    )

    reasons = set(response.candidates[0].match_reasons)
    assert "pubmed_neighbor_score" in reasons
    assert "full_text_available" in reasons
    assert "shared_publication_type" in reasons
    assert "guideline_or_consensus_match" in reasons
    assert "pediatric_match" in reasons
    assert "treatment_match" in reasons
    assert response.meta.response_mode == "compact"


@pytest.mark.asyncio
async def test_metadata_full_text_pmc_candidate_emits_open_access_reason() -> None:
    service = RelatedEvidenceService(
        discovery_service=IntentDiscovery(),
        metadata_service=IntentMetadata(),
        citation_graph_service=IntentCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="1",
            max_results=5,
            include_citation_neighbors=False,
        )
    )

    reasons = set(response.candidates[0].match_reasons)
    assert "full_text_available" in reasons
    assert "open_access_available" in reasons
