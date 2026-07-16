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
    assert "index_review_evidence" in response.meta["next_commands"][1]
    assert "FMF MEFV VUS colchicine" in response.meta["next_commands"][3]


@pytest.mark.asyncio
async def test_readonly_corpus_suggestion_ends_in_direct_passage_retrieval() -> None:
    class FakeSearch:
        async def search(self, query: str, *, limit: int, sort: str | None):
            return {"results": [{"pmid": "1", "title": "FMF cohort"}]}

    class FakeMetadata:
        async def get_metadata(self, request):
            return PublicationMetadataResponse(metadata=[], failed_pmids={}, _meta={})

    class FakePreflight:
        async def preflight_pmids(self, pmids: list[str]) -> list[SourceCoverageHint]:
            return []

    service = CorpusSuggestionService(
        search_client=FakeSearch(),
        metadata_service=FakeMetadata(),
        source_preflight_service=FakePreflight(),
    )

    response = await service.suggest(
        CorpusSuggestionRequest(question="FMF cohort", max_pmids=1),
        profile="readonly",
    )

    assert response.meta["next_commands"] == [
        "get_publication_metadata(pmids=['1'])",
        "preflight_review_sources(pmids=['1'])",
        "get_publication_passages(pmids=['1'])",
    ]


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


@pytest.mark.asyncio
async def test_corpus_suggestion_discloses_relevance_and_omits_weak_candidates() -> None:
    class FakeSearch:
        async def search(self, query: str, *, limit: int, sort: str | None):
            return {
                "results": [
                    {
                        "pmid": "26802180",
                        "title": "EULAR recommendations for familial Mediterranean fever",
                    },
                    {"pmid": "33726481", "title": "MEFV variant cohort registry"},
                    {"pmid": "888", "title": "CRISPR oncology cell line assay"},
                ]
            }

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
            question="FMF MEFV colchicine guideline",
            max_pmids=4,
            must_include_pmids=["999"],
            include_metadata=False,
        )
    )

    assert response.candidate_pmids == ["999", "26802180", "33726481"]
    assert "888" not in {candidate.pmid for candidate in response.candidates}
    required = next(candidate for candidate in response.candidates if candidate.pmid == "999")
    guideline = next(candidate for candidate in response.candidates if candidate.pmid == "26802180")
    cohort = next(candidate for candidate in response.candidates if candidate.pmid == "33726481")
    assert required.matched_terms == []
    assert required.matched_intents == ["must_include"]
    assert {"familial mediterranean fever", "guideline"} <= set(guideline.matched_terms)
    assert "guideline" in guideline.matched_intents
    assert "mefv" in cohort.matched_terms
    assert "cohort" in cohort.matched_intents


@pytest.mark.asyncio
async def test_corpus_suggestion_relevance_ignores_stopword_only_overlap() -> None:
    class FakeSearch:
        async def search(self, query: str, *, limit: int, sort: str | None):
            return {
                "results": [
                    {"pmid": "26802180", "title": "EULAR recommendations for FMF"},
                    {"pmid": "888", "title": "Children with nutrition from school programs"},
                ]
            }

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
            question="children with FMF from MEFV guideline",
            max_pmids=3,
            include_metadata=False,
        )
    )

    assert response.candidate_pmids == ["26802180"]

    required_response = await service.suggest(
        CorpusSuggestionRequest(
            question="children with FMF from MEFV guideline",
            max_pmids=3,
            must_include_pmids=["888"],
            include_metadata=False,
        )
    )

    assert required_response.candidate_pmids == ["888", "26802180"]
    required = next(
        candidate for candidate in required_response.candidates if candidate.pmid == "888"
    )
    assert required.matched_terms == []
    assert required.matched_intents == ["must_include"]


@pytest.mark.asyncio
async def test_corpus_suggestion_relevance_requires_topical_overlap_not_role_only() -> None:
    class FakeSearch:
        async def search(self, query: str, *, limit: int, sort: str | None):
            return {
                "results": [
                    {
                        "pmid": "26802180",
                        "title": "EULAR recommendations for MEFV familial Mediterranean fever",
                    },
                    {"pmid": "888", "title": "Treatment recommendations for asthma"},
                    {"pmid": "889", "title": "National diabetes registry outcomes"},
                ]
            }

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
            question="MEFV FMF EULAR guidance",
            max_pmids=4,
            include_metadata=False,
        )
    )

    assert response.candidate_pmids == ["26802180"]
    guideline = response.candidates[0]
    assert {"mefv", "eular", "familial mediterranean fever"} <= set(guideline.matched_terms)
    assert "guideline" in guideline.matched_intents

    required_response = await service.suggest(
        CorpusSuggestionRequest(
            question="MEFV FMF EULAR guidance",
            max_pmids=4,
            must_include_pmids=["888"],
            include_metadata=False,
        )
    )

    assert required_response.candidate_pmids == ["888", "26802180"]
    required = next(
        candidate for candidate in required_response.candidates if candidate.pmid == "888"
    )
    assert required.matched_terms == []
    assert {"must_include", "guideline"} <= set(required.matched_intents)
