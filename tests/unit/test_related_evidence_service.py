from __future__ import annotations

import asyncio

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


class AsyncStartBarrier:
    def __init__(self, expected: int) -> None:
        self.expected = expected
        self.started: list[str] = []
        self.release = asyncio.Event()

    async def arrive(self, name: str) -> None:
        self.started.append(name)
        if len(self.started) >= self.expected:
            self.release.set()
        await self.release.wait()


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


class CoordinatedDiscovery:
    def __init__(self, barrier: AsyncStartBarrier) -> None:
        self.barrier = barrier

    async def find_related_article_scores(
        self,
        pmids: list[str],
        limit: int,
    ) -> list[RelatedArticleScoreRecord]:
        await self.barrier.arrive("elink")
        return [RelatedArticleScoreRecord(source_pmid="123", pmid="111", neighbor_score=900)]


class CoordinatedMetadata:
    def __init__(self, barrier: AsyncStartBarrier) -> None:
        self.barrier = barrier

    async def get_metadata(self, request):
        if request.pmids == ["123"]:
            await self.barrier.arrive("source_metadata")
        records = {
            "123": PublicationMetadata(
                pmid="123",
                title="Seed review",
                journal="Seed Journal",
                pub_year=2021,
                publication_types=["Review"],
                coverage="abstract_only",
            ),
            "111": PublicationMetadata(
                pmid="111",
                title="Review paper",
                pub_year=2024,
                publication_types=["Review"],
                coverage="abstract_only",
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


class CoordinatedCitationGraph:
    def __init__(self, barrier: AsyncStartBarrier) -> None:
        self.barrier = barrier

    async def get_citation_graph(self, request):
        await self.barrier.arrive("citation_graph")
        return PublicationCitationGraphResponse(
            source=LiteraturePaper(pmid=request.pmid),
            candidate_pmids=["333"],
        )


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


class ScoreRangeDiscovery:
    async def find_related_article_scores(
        self,
        pmids: list[str],
        limit: int,
    ) -> list[RelatedArticleScoreRecord]:
        return [
            RelatedArticleScoreRecord(source_pmid="123", pmid="111", neighbor_score=10),
            RelatedArticleScoreRecord(source_pmid="123", pmid="222", neighbor_score=30),
        ]


class FakeMetadata:
    async def get_metadata(self, request):
        assert request.pmids
        records = {
            "123": PublicationMetadata(
                pmid="123",
                title="Seed review",
                journal="Seed Journal",
                pub_year=2021,
                publication_types=["Review"],
                coverage="abstract_only",
            ),
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


class CoverageWarningMetadata(FakeMetadata):
    async def get_metadata(self, request):
        response = await super().get_metadata(request)
        return response.model_copy(
            update={
                "meta": {
                    **response.meta,
                    "warnings": ["coverage_lookup_failed"],
                }
            }
        )


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


class ManyCandidateDiscovery:
    async def find_related_article_scores(
        self,
        pmids: list[str],
        limit: int,
    ) -> list[RelatedArticleScoreRecord]:
        assert pmids == ["123"]
        return [
            RelatedArticleScoreRecord(
                source_pmid="123",
                pmid=str(100000 + index),
                neighbor_score=1000 - index,
            )
            for index in range(100)
        ]


class ManyCandidateCitationGraph:
    async def get_citation_graph(self, request):
        return PublicationCitationGraphResponse(
            source=LiteraturePaper(pmid=request.pmid),
            candidate_pmids=[str(200000 + index) for index in range(110)],
        )


class RecordingMetadata:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def get_metadata(self, request):
        self.calls.append(list(request.pmids))
        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid=pmid,
                    title=f"Resolved metadata {pmid}",
                    pub_year=2024,
                    coverage="abstract_only",
                )
                for pmid in request.pmids
            ],
        )


class RecordingRequestMetadata:
    def __init__(self) -> None:
        self.requests = []

    async def get_metadata(self, request):
        self.requests.append(request)
        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid=pmid,
                    title=f"Resolved metadata {pmid}",
                    pub_year=2024,
                    coverage="abstract_only",
                )
                for pmid in request.pmids
            ],
        )


class PartialFailureMetadata:
    def __init__(self) -> None:
        self.requests = []

    async def get_metadata(self, request):
        self.requests.append(request)
        if len(self.requests) == 3:
            raise RuntimeError("metadata unavailable")
        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid=pmid,
                    title=f"Resolved metadata {pmid}",
                    pub_year=2024,
                    coverage="abstract_only",
                )
                for pmid in request.pmids
            ],
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
async def test_related_evidence_runs_independent_network_inputs_concurrently() -> None:
    barrier = AsyncStartBarrier(expected=3)
    service = RelatedEvidenceService(
        discovery_service=CoordinatedDiscovery(barrier),
        metadata_service=CoordinatedMetadata(barrier),
        citation_graph_service=CoordinatedCitationGraph(barrier),
    )

    response = await asyncio.wait_for(
        service.find_candidates(RelatedEvidenceCandidatesRequest(pmid="123")),
        timeout=0.5,
    )

    assert set(barrier.started) == {"elink", "source_metadata", "citation_graph"}
    assert response.source.title == "Seed review"
    assert set(response.candidate_pmids) == {"111", "333"}


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
async def test_related_evidence_resolves_source_metadata() -> None:
    service = RelatedEvidenceService(
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
        citation_graph_service=FakeCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(pmid="123", include_citation_neighbors=False)
    )

    assert response.source.title == "Seed review"
    assert response.source.journal == "Seed Journal"
    assert response.source.year == 2021
    assert response.source.publication_types == ["Review"]


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
async def test_related_evidence_batches_large_metadata_candidate_sets() -> None:
    metadata = RecordingMetadata()
    service = RelatedEvidenceService(
        discovery_service=ManyCandidateDiscovery(),
        metadata_service=metadata,
        citation_graph_service=ManyCandidateCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="123",
            max_results=25,
            include_citation_neighbors=True,
        )
    )

    assert [len(call) for call in metadata.calls] == [1, 100, 100, 10]
    assert len(response.candidates) == 25
    assert all(
        candidate.paper.status == "resolved_metadata_only" for candidate in response.candidates
    )
    assert all(candidate.paper.title for candidate in response.candidates)
    assert not any(warning.provider == "pubmed_metadata" for warning in response.meta.warnings)


@pytest.mark.asyncio
async def test_related_evidence_candidate_metadata_preserves_internal_options() -> None:
    metadata = RecordingRequestMetadata()
    service = RelatedEvidenceService(
        discovery_service=ManyCandidateDiscovery(),
        metadata_service=metadata,
        citation_graph_service=ManyCandidateCitationGraph(),
    )

    await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="123",
            max_results=25,
            include_citation_neighbors=True,
        )
    )

    candidate_requests = metadata.requests[1:]
    assert [len(request.pmids) for request in candidate_requests] == [100, 100, 10]
    assert all(request.include_mesh is False for request in candidate_requests)
    assert all(request.include_publication_types is True for request in candidate_requests)
    assert all(request.include_citations == "none" for request in candidate_requests)
    assert all(request.include_coverage is True for request in candidate_requests)


@pytest.mark.asyncio
async def test_related_evidence_partial_metadata_batch_failure_keeps_successful_candidates() -> (
    None
):
    metadata = PartialFailureMetadata()
    service = RelatedEvidenceService(
        discovery_service=ManyCandidateDiscovery(),
        metadata_service=metadata,
        citation_graph_service=ManyCandidateCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="123",
            max_results=25,
            include_citation_neighbors=True,
        )
    )

    assert [len(request.pmids) for request in metadata.requests] == [1, 100, 100, 10]
    assert response.candidates
    assert any(candidate.paper.title for candidate in response.candidates)
    assert any(
        warning.provider == "pubmed_metadata" and warning.status == "provider_failed"
        for warning in response.meta.warnings
    )
    warning_messages = [warning.message for warning in response.meta.warnings]
    assert "PubMed metadata warning: pubmed_metadata_batch_failed" in warning_messages
    assert "Metadata lookup failed for 100 PMID(s)." in warning_messages


@pytest.mark.asyncio
async def test_related_evidence_metadata_warning_includes_stable_warning_code() -> None:
    service = RelatedEvidenceService(
        discovery_service=FakeDiscovery(),
        metadata_service=CoverageWarningMetadata(),
        citation_graph_service=FakeCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="123",
            max_results=5,
        )
    )

    metadata_warnings = [
        warning for warning in response.meta.warnings if warning.provider == "pubmed_metadata"
    ]
    assert metadata_warnings
    assert {warning.code for warning in metadata_warnings} == {"coverage_lookup_failed"}
    assert metadata_warnings[0].next_steps
    assert "retry" in metadata_warnings[0].next_steps[0].casefold()


@pytest.mark.asyncio
async def test_related_evidence_compact_populates_cache_and_omitted_candidate_count() -> None:
    metadata = RecordingMetadata()
    service = RelatedEvidenceService(
        discovery_service=ManyCandidateDiscovery(),
        metadata_service=metadata,
        citation_graph_service=ManyCandidateCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="123",
            max_results=10,
            response_mode="compact",
            include_citation_neighbors=True,
        )
    )

    assert response.meta.request_signature is not None
    assert response.meta.cache_key == response.meta.request_signature
    assert response.meta.snapshot_date is not None
    assert response.meta.source_versions["pubmed"] == "live"
    assert response.meta.truncated is True
    assert response.meta.omitted_counts["candidates"] > 0
    assert response.omitted_candidate_preview
    assert len(response.omitted_candidate_preview) <= 5
    assert response.omitted_candidate_preview[0].pmid not in response.candidate_pmids
    assert any(
        command["arguments"]["response_mode"] == "full" for command in response.meta.next_commands
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
async def test_metadata_full_text_pmc_candidate_does_not_imply_open_access_reason() -> None:
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
    assert "open_access_available" not in reasons
    assert response.candidates[0].paper.availability.has_pmc_full_text is True
    assert response.candidates[0].paper.availability.is_open_access is False


@pytest.mark.asyncio
async def test_related_evidence_adds_normalized_neighbor_score_and_signals() -> None:
    service = RelatedEvidenceService(
        discovery_service=ScoreRangeDiscovery(),
        metadata_service=FakeMetadata(),
        citation_graph_service=FakeCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="123",
            include_citation_neighbors=False,
            max_results=2,
        )
    )

    by_pmid = {candidate.paper.pmid: candidate for candidate in response.candidates}
    assert by_pmid["222"].normalized_neighbor_score == 1.0
    assert by_pmid["111"].normalized_neighbor_score == 0.0
    assert by_pmid["222"].signals == by_pmid["222"].match_reasons


@pytest.mark.asyncio
async def test_related_evidence_compact_uses_normalized_neighbor_score() -> None:
    service = RelatedEvidenceService(
        discovery_service=ScoreRangeDiscovery(),
        metadata_service=FakeMetadata(),
        citation_graph_service=FakeCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="123",
            response_mode="compact",
            include_citation_neighbors=False,
        )
    )
    payload = response.model_dump(by_alias=True)

    assert payload["candidates"][0]["normalized_neighbor_score"] is not None
    assert "pubmed_neighbor_score" not in payload["candidates"][0]
    assert "score" not in payload["candidates"][0]
    assert "0 does not mean irrelevant" in payload["score_explanation"]
