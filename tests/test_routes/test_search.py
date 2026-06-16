"""Tests for publication search route endpoints."""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from pubtator_link.api.client import PubTator3Client
from pubtator_link.server_manager import UnifiedServerManager
from tests.fixtures.api_responses import MockPubTatorResponses

# Mock response for search testing
MOCK_SEARCH_RESPONSE = MockPubTatorResponses.search_publications_response()


@pytest.fixture
def test_client():
    """Create test client."""
    manager = UnifiedServerManager()
    app = manager.create_app()
    return TestClient(app)


class TestSearchRoutes:
    """Test publication search endpoints."""

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_free_text(self, mock_search, test_client):
        """Test free text publication search."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get(
            "/api/search/", params={"text": "breast cancer treatment", "page": 1}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["query"] == "breast cancer treatment"
        assert len(data["results"]) == 3  # Updated to match fixture
        assert data["total_results"] == 150
        assert data["page"] == 1
        assert data["per_page"] == 20
        assert data["total_pages"] == 8  # ceil(150/20)

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_entity_id(self, mock_search, test_client):
        """Test entity ID publication search."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get(
            "/api/search/", params={"text": "@CHEMICAL_remdesivir", "page": 1}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "@CHEMICAL_remdesivir"
        assert "37711410" in str(data["results"][0]["pmid"])

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_boolean_query(self, mock_search, test_client):
        """Test boolean search query."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get(
            "/api/search/",
            params={"text": "@CHEMICAL_Doxorubicin AND @DISEASE_Neoplasms", "page": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert "AND" in data["query"]

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_relation_query(self, mock_search, test_client):
        """Test relation search query."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get(
            "/api/search/",
            params={"text": "relations:treat|@CHEMICAL_remdesivir|Disease", "page": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert "relations:treat" in data["query"]

    def test_search_publications_invalid_page(self, test_client):
        """Test search with invalid page number."""
        response = test_client.get("/api/search/", params={"text": "cancer", "page": 0})

        assert response.status_code == 422  # Pydantic validation error

    def test_search_publications_empty_query(self, test_client):
        """Test search with empty query."""
        response = test_client.get("/api/search/", params={"text": "", "page": 1})

        assert response.status_code == 422  # Pydantic validation error

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_with_sort_date_desc(self, mock_search, test_client):
        """Test search with date descending sort."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get(
            "/api/search/",
            params={"text": "breast cancer", "page": 1, "sort": "date desc"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["sort_order"] == "date desc"
        # Verify the API client was called with the sort parameter
        mock_search.assert_called_once_with(
            text="breast cancer", page=1, sort="date desc", filters=None, sections=None
        )

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_with_sort_score_asc(self, mock_search, test_client):
        """Test search with score ascending sort."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get(
            "/api/search/",
            params={"text": "BRCA1", "page": 1, "sort": "score asc"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["sort_order"] == "score asc"
        mock_search.assert_called_once_with(
            text="BRCA1", page=1, sort="score asc", filters=None, sections=None
        )

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_default_sort(self, mock_search, test_client):
        """Test search without sort parameter (default behavior)."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get(
            "/api/search/",
            params={"text": "covid", "page": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["sort_order"] is None  # No sort applied
        mock_search.assert_called_once_with(
            text="covid", page=1, sort=None, filters=None, sections=None
        )

    def test_search_publications_invalid_sort(self, test_client):
        """Test search with invalid sort parameter."""
        response = test_client.get(
            "/api/search/",
            params={"text": "cancer", "page": 1, "sort": "invalid_sort"},
        )

        assert response.status_code == 422  # Pydantic validation error

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_default_page(self, mock_search, test_client):
        """Test search with default page number."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get("/api/search/", params={"text": "cancer"})

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_high_page_number(self, mock_search, test_client):
        """Test search with high page number."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get("/api/search/", params={"text": "cancer", "page": 5})

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 5

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_gene_entity_query(self, mock_search, test_client):
        """Test search with gene entity ID."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get("/api/search/", params={"text": "@GENE_BRCA1", "page": 1})

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "@GENE_BRCA1"
        assert data["success"] is True

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_disease_entity_query(self, mock_search, test_client):
        """Test search with disease entity ID."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get("/api/search/", params={"text": "@DISEASE_COVID_19", "page": 1})

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "@DISEASE_COVID_19"

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_complex_boolean_query(self, mock_search, test_client):
        """Test search with complex boolean query."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get(
            "/api/search/",
            params={
                "text": "(@GENE_BRCA1 OR @GENE_BRCA2) AND @DISEASE_Breast_Neoplasms",
                "page": 1,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "OR" in data["query"]
        assert "AND" in data["query"]

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_no_results(self, mock_search, test_client):
        """Test search with no results."""
        empty_response = {
            "results": [],
            "total": 0,
            "per_page": 20,
        }
        mock_search.return_value = empty_response

        response = test_client.get("/api/search/", params={"text": "very_rare_nonexistent_term"})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["results"]) == 0
        assert data["total_results"] == 0

    def test_search_publications_missing_text_parameter(self, test_client):
        """Test search without text parameter."""
        response = test_client.get("/api/search/", params={"page": 1})

        assert response.status_code == 422  # Validation error

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_unicode_query(self, mock_search, test_client):
        """Test search with unicode characters."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get("/api/search/", params={"text": "癌症 breast cancer"})

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "癌症 breast cancer"

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_special_characters(self, mock_search, test_client):
        """Test search with special characters."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get(
            "/api/search/", params={"text": "breast cancer (hereditary) & mutations"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "hereditary" in data["query"]

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_pagination_calculation(self, mock_search, test_client):
        """Test pagination calculation."""
        # Mock response with specific totals for pagination testing
        pagination_response = {
            "results": [],
            "total": 157,  # Not evenly divisible by 20
            "per_page": 20,
        }
        mock_search.return_value = pagination_response

        response = test_client.get("/api/search/", params={"text": "cancer", "page": 8})

        assert response.status_code == 200
        data = response.json()
        assert data["total_pages"] == 8  # ceil(157/20) = 8
        assert data["total_results"] == 157

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_relation_complex_query(self, mock_search, test_client):
        """Test complex relation query."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get(
            "/api/search/",
            params={
                "text": "relations:ANY|@CHEMICAL_aspirin|@DISEASE_Cardiovascular_Diseases",
                "page": 1,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "relations:ANY" in data["query"]

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_maps_pubtator3_count_and_metadata(self, mock_search, test_client):
        """Test PubTator3 count metadata and structured result metadata mapping."""
        mock_search.return_value = {
            "results": [
                {
                    "pmid": 39596913,
                    "title": "Guideline title",
                    "journal": "Ann Rheum Dis",
                    "authors": ["Smith J"],
                    "date": "2024",
                    "doi": "10.1000/test",
                    "pmcid": "PMC123",
                    "meta_date_publication": "2024 Oct 22",
                    "meta_volume": "83",
                    "meta_issue": "11",
                    "meta_pages": "123-130",
                    "publication_types": ["Guideline", "Practice Guideline"],
                    "citations": {"nlm": "Ann Rheum Dis. PMID: 39596913"},
                    "score": 12.5,
                }
            ],
            "count": 2776,
            "total_pages": 278,
            "page_size": 10,
        }

        response = test_client.get("/api/search/", params={"text": "guideline"})

        assert response.status_code == 200
        data = response.json()
        item = data["results"][0]
        assert data["total_results"] == 2776
        assert data["total_pages"] == 278
        assert data["per_page"] == 10
        assert item["pmid"] == "39596913"
        assert item["date"] == "2024"
        assert item["pub_date"] == "2024 Oct 22"
        assert item["doi"] == "10.1000/test"
        assert item["pmcid"] == "PMC123"
        assert item["volume"] == "83"
        assert item["issue"] == "11"
        assert item["pages"] == "123-130"
        assert item["publication_types"] == ["Guideline", "Practice Guideline"]
        assert item["citations"]["nlm"].endswith("39596913")

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_can_attach_preflight_coverage(self, mock_search, test_client):
        """Test route can add source coverage hints to search results."""
        from pubtator_link.api.routes.dependencies import get_source_preflight_service
        from pubtator_link.models.review_rerag import SourceCoverageHint

        class FakePreflight:
            async def preflight_pmids(self, pmids: list[str]) -> list[SourceCoverageHint]:
                return [
                    SourceCoverageHint(
                        pmid=pmids[0],
                        expected_coverage="abstract_only",
                        coverage_reason="no_pmcid",
                    )
                ]

        async def fake_source_preflight_service() -> FakePreflight:
            return FakePreflight()

        mock_search.return_value = {
            "results": [{"pmid": "39540697", "title": "FMF in Childhood"}],
            "count": 1,
            "total_pages": 1,
            "page_size": 10,
        }
        test_client.app.dependency_overrides[get_source_preflight_service] = (
            fake_source_preflight_service
        )

        try:
            response = test_client.get(
                "/api/search/",
                params={"text": "FMF", "coverage": "preflight"},
            )
        finally:
            test_client.app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["results"][0]["coverage_hint"]["expected_coverage"] == "abstract_only"
        assert data["results"][0]["preflight_coverage_guess"] == "abstract_only"
        assert data["results"][0]["preflight_coverage_reason"] == "no_pmcid"
        assert data["results"][0]["preflight_confidence"] == "medium"

    @patch.object(PubTator3Client, "search_publications")
    def test_search_preflight_failure_returns_structured_fields(self, mock_search, test_client):
        """Test coverage preflight failures are structured and non-fatal."""
        from pubtator_link.api.routes.dependencies import get_source_preflight_service

        class FakePreflight:
            async def preflight_pmids(self, pmids: list[str]):
                raise TimeoutError("preflight timed out")

        async def fake_source_preflight_service() -> FakePreflight:
            return FakePreflight()

        mock_search.return_value = {
            "results": [{"pmid": "39540697", "title": "FMF in Childhood"}],
            "count": 1,
            "total_pages": 1,
            "page_size": 10,
        }
        test_client.app.dependency_overrides[get_source_preflight_service] = (
            fake_source_preflight_service
        )

        try:
            response = test_client.get(
                "/api/search/",
                params={"text": "FMF", "coverage": "preflight"},
            )
        finally:
            test_client.app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["preflight_error_reason"] == "timeout"
        assert data["preflight_error_code"] == "coverage_preflight_timeout"
        assert data["preflight_error"] == {
            "code": "coverage_preflight_timeout",
            "reason": "timeout",
            "retryable": True,
            "message": "Coverage preflight timed out; retrying may succeed.",
        }

    @patch.object(PubTator3Client, "search_publications")
    def test_search_preflight_internal_error_is_marked_non_retryable(
        self, mock_search, test_client
    ):
        """Test coverage preflight internal errors tell clients not to retry blindly."""
        from pubtator_link.api.routes.dependencies import get_source_preflight_service

        class FakePreflight:
            async def preflight_pmids(self, pmids: list[str]):
                raise RuntimeError("unexpected parser state")

        async def fake_source_preflight_service() -> FakePreflight:
            return FakePreflight()

        mock_search.return_value = {
            "results": [{"pmid": "39540697", "title": "FMF in Childhood"}],
            "count": 1,
            "total_pages": 1,
            "page_size": 10,
        }
        test_client.app.dependency_overrides[get_source_preflight_service] = (
            fake_source_preflight_service
        )

        try:
            response = test_client.get(
                "/api/search/",
                params={"text": "FMF", "coverage": "preflight"},
            )
        finally:
            test_client.app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["preflight_error_code"] == "coverage_preflight_internal_error"
        assert data["preflight_error"]["retryable"] is False

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_can_enrich_basic_metadata(self, mock_search, test_client):
        from pubtator_link.api.routes.dependencies import get_publication_metadata_service
        from pubtator_link.models.publication_metadata import (
            PublicationAuthor,
            PublicationMetadata,
            PublicationMetadataResponse,
        )

        class FakeMetadataService:
            async def get_metadata(self, request):
                assert request.pmids == ["33454820"]
                assert request.include_mesh is False
                return PublicationMetadataResponse(
                    metadata=[
                        PublicationMetadata(
                            pmid="33454820",
                            authors=[PublicationAuthor(last_name="Kavrul Kayaalp", initials="GK")],
                            journal="Rheumatology International",
                            pub_year=2022,
                        )
                    ],
                    _meta={"next_commands": []},
                )

        async def fake_metadata_service() -> FakeMetadataService:
            return FakeMetadataService()

        mock_search.return_value = {
            "results": [{"pmid": "33454820", "title": "FMF"}],
            "count": 1,
            "total_pages": 1,
            "page_size": 10,
        }
        test_client.app.dependency_overrides[get_publication_metadata_service] = (
            fake_metadata_service
        )

        try:
            response = test_client.get(
                "/api/search/",
                params={"text": "MEFV", "metadata": "basic", "response_mode": "compact"},
            )
        finally:
            test_client.app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["results"][0]
        assert item["authors"] == []
        assert item["first_author_et_al"] == "Kavrul Kayaalp GK"
        assert item["journal"] == "Rheumatology International"

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_metadata_batches_limit_none_over_public_cap(
        self, mock_search, test_client
    ):
        from pubtator_link.api.routes.dependencies import get_publication_metadata_service
        from pubtator_link.models.publication_metadata import (
            PublicationMetadata,
            PublicationMetadataRequest,
            PublicationMetadataResponse,
        )

        class RecordingMetadataService:
            def __init__(self) -> None:
                self.requests: list[PublicationMetadataRequest] = []

            async def get_metadata(
                self, request: PublicationMetadataRequest
            ) -> PublicationMetadataResponse:
                self.requests.append(request)
                return PublicationMetadataResponse(
                    metadata=[
                        PublicationMetadata(pmid=pmid, title=f"Metadata {pmid}")
                        for pmid in request.pmids
                    ],
                    _meta={"next_commands": []},
                )

        metadata_service = RecordingMetadataService()

        async def fake_metadata_service() -> RecordingMetadataService:
            return metadata_service

        mock_search.return_value = {
            "results": [
                {"pmid": str(700000 + index), "title": f"Result {index}"} for index in range(105)
            ],
            "count": 105,
            "total_pages": 1,
            "page_size": 105,
        }
        test_client.app.dependency_overrides[get_publication_metadata_service] = (
            fake_metadata_service
        )

        try:
            response = test_client.get(
                "/api/search/",
                params={"text": "MEFV", "metadata": "basic"},
            )
        finally:
            test_client.app.dependency_overrides.clear()

        assert response.status_code == 200
        assert len(response.json()["results"]) == 105
        assert [len(request.pmids) for request in metadata_service.requests] == [100, 5]
        assert all(request.include_mesh is False for request in metadata_service.requests)
        assert all(request.include_citations == "none" for request in metadata_service.requests)
        assert all(request.include_coverage is False for request in metadata_service.requests)

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_merges_flat_filters(self, mock_search, test_client):
        """Test route merges raw JSON filters with flat filter query params."""
        mock_search.return_value = {"results": [], "count": 0, "total_pages": 0, "page_size": 10}

        response = test_client.get(
            "/api/search/",
            params=[
                ("text", "guideline"),
                ("filters", '{"journal":["Ann Rheum Dis"]}'),
                ("publication_types", "Guideline"),
                ("publication_types", "Practice Guideline"),
                ("year_min", "2020"),
                ("year_max", "2026"),
            ],
        )

        assert response.status_code == 200
        call_kwargs = mock_search.call_args.kwargs
        # Year ranges are applied locally (PubTator3 has no server-side range
        # support), so only journal + type reach the upstream filters param.
        assert json.loads(call_kwargs["filters"]) == {
            "journal": ["Ann Rheum Dis"],
            "type": ["Guideline", "Practice Guideline"],
        }

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_applies_year_range_locally(self, mock_search, test_client):
        """A year range is trimmed locally since PubTator3 has no range support."""
        mock_search.return_value = {
            "results": [
                {"pmid": "1", "title": "Recent", "date": "2024-01-01T00:00:00Z"},
                {"pmid": "2", "title": "Old", "date": "2015-01-01T00:00:00Z"},
            ],
            "count": 2,
            "total_pages": 1,
            "page_size": 10,
        }

        response = test_client.get(
            "/api/search/",
            params=[("text", "CFTR"), ("year_min", "2020")],
        )

        assert response.status_code == 200
        # No unsupported year object is sent upstream.
        assert mock_search.call_args.kwargs["filters"] is None
        pmids = [r["pmid"] for r in response.json()["results"]]
        assert pmids == ["1"]

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_rejects_flat_filter_conflict(self, mock_search, test_client):
        """Test route rejects duplicate raw and flat publication type filters."""
        response = test_client.get(
            "/api/search/",
            params=[
                ("text", "guideline"),
                ("filters", '{"type":["Review"]}'),
                ("publication_types", "Guideline"),
            ],
        )

        assert response.status_code == 422
        assert "type" in response.text
        mock_search.assert_not_called()

    @pytest.mark.parametrize(
        "filters",
        [
            '{"year":{"min":1700}}',
            '{"year":{"max":9999}}',
            '{"year":{"min":2026,"max":2020}}',
        ],
    )
    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_rejects_raw_year_filter_validation(
        self, mock_search, test_client, filters
    ):
        """Test route rejects invalid raw year filters before calling PubTator."""
        response = test_client.get(
            "/api/search/",
            params={
                "text": "guideline",
                "filters": filters,
            },
        )

        assert response.status_code == 422
        assert "year" in response.text
        mock_search.assert_not_called()
