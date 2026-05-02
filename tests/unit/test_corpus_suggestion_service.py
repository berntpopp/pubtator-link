import pytest

from pubtator_link.models.corpus_suggestion import CorpusSuggestionRequest
from pubtator_link.models.publication_metadata import (
    PublicationMetadata,
    PublicationMetadataResponse,
)
from pubtator_link.models.review_rerag import SourceCoverageHint
from pubtator_link.services.corpus_suggestion import CorpusSuggestionService


def test_corpus_suggestion_request_clamps_max_pmids() -> None:
    request = CorpusSuggestionRequest(question="FMF MEFV VUS colchicine", max_pmids=50)

    assert request.max_pmids == 20


@pytest.mark.asyncio
async def test_corpus_suggestion_service_deduplicates_and_assigns_roles() -> None:
    class FakeSearch:
        def __init__(self) -> None:
            self.queries: list[str] = []

        async def search(self, query: str, *, limit: int, sort: str | None):
            self.queries.append(query)
            return {
                "results": [
                    {"pmid": "26802180", "title": "EULAR recommendations for FMF", "score": 50.0},
                    {"pmid": "33726481", "title": "VUS cohort", "score": 40.0},
                    {"pmid": "26802180", "title": "Duplicate", "score": 20.0},
                ]
            }

    class FakeMetadata:
        async def get_metadata(self, request):
            return PublicationMetadataResponse(
                metadata=[
                    PublicationMetadata(
                        pmid="26802180",
                        title="EULAR recommendations for FMF",
                        publication_types=["Practice Guideline"],
                    ),
                    PublicationMetadata(
                        pmid="33726481",
                        title="VUS cohort",
                        publication_types=["Journal Article"],
                    ),
                ],
                failed_pmids={},
                _meta={"next_commands": []},
            )

    class FakePreflight:
        async def preflight_pmids(self, pmids: list[str]) -> list[SourceCoverageHint]:
            return [
                SourceCoverageHint(
                    pmid=pmid,
                    expected_coverage="abstract_only",
                    coverage_reason="abstract_fallback_used",
                )
                for pmid in pmids
            ]

    search = FakeSearch()
    service = CorpusSuggestionService(
        search_client=search,
        metadata_service=FakeMetadata(),
        source_preflight_service=FakePreflight(),
    )

    response = await service.suggest(
        CorpusSuggestionRequest(question="FMF MEFV VUS colchicine", max_pmids=2).model_copy(
            update={"entity_ids": ["@GENE_MEFV"]}
        )
    )

    assert response.candidate_pmids == ["26802180", "33726481"]
    assert any("@GENE_MEFV" in query for query in search.queries)
    assert response.candidates[0].role == "guideline"
    assert response.candidates[1].role == "cohort"
    assert "pubtator.index_review_evidence" in response.meta["next_commands"][1]
    assert "FMF MEFV VUS colchicine" in response.meta["next_commands"][3]


@pytest.mark.asyncio
async def test_corpus_suggestion_caps_must_include_pmids() -> None:
    class FakeSearch:
        async def search(self, query: str, *, limit: int, sort: str | None):
            return {"results": [{"pmid": "4", "title": "Extra result"}]}

    class FakeMetadata:
        def __init__(self) -> None:
            self.requested_pmids: list[str] = []

        async def get_metadata(self, request):
            self.requested_pmids = request.pmids
            return PublicationMetadataResponse(metadata=[], failed_pmids={}, _meta={})

    class FakePreflight:
        def __init__(self) -> None:
            self.requested_pmids: list[str] = []

        async def preflight_pmids(self, pmids: list[str]) -> list[SourceCoverageHint]:
            self.requested_pmids = pmids
            return []

    metadata = FakeMetadata()
    preflight = FakePreflight()
    service = CorpusSuggestionService(
        search_client=FakeSearch(),
        metadata_service=metadata,
        source_preflight_service=preflight,
    )

    response = await service.suggest(
        CorpusSuggestionRequest(
            question="FMF MEFV variants",
            max_pmids=2,
            must_include_pmids=["1", "2", "3"],
        )
    )

    assert response.candidate_pmids == ["1", "2"]
    assert metadata.requested_pmids == ["1", "2"]
    assert preflight.requested_pmids == ["1", "2"]


@pytest.mark.asyncio
async def test_corpus_suggestion_skips_metadata_lookup_when_disabled() -> None:
    class FakeSearch:
        async def search(self, query: str, *, limit: int, sort: str | None):
            return {"results": [{"pmid": "1", "title": "Large FMF cohort registry"}]}

    class FakeMetadata:
        async def get_metadata(self, request):
            raise AssertionError("metadata should not be fetched")

    class FakePreflight:
        async def preflight_pmids(self, pmids: list[str]) -> list[SourceCoverageHint]:
            return []

    service = CorpusSuggestionService(
        search_client=FakeSearch(),
        metadata_service=FakeMetadata(),
        source_preflight_service=FakePreflight(),
    )

    response = await service.suggest(
        CorpusSuggestionRequest(
            question="FMF MEFV variants",
            max_pmids=1,
            include_metadata=False,
        )
    )

    assert response.candidate_pmids == ["1"]
    assert response.candidates[0].metadata is None
    assert response.candidates[0].title == "Large FMF cohort registry"
    assert response.candidates[0].role == "cohort"
