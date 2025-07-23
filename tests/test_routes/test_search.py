"""Tests for publication search route endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from pubtator_link.server_manager import UnifiedServerManager
from pubtator_link.api.client import PubTator3Client
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

        response = test_client.get(
            "/api/search/", params={"text": "@GENE_BRCA1", "page": 1}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "@GENE_BRCA1"
        assert data["success"] is True

    @patch.object(PubTator3Client, "search_publications")
    def test_search_publications_disease_entity_query(self, mock_search, test_client):
        """Test search with disease entity ID."""
        mock_search.return_value = MOCK_SEARCH_RESPONSE

        response = test_client.get(
            "/api/search/", params={"text": "@DISEASE_COVID_19", "page": 1}
        )

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

        response = test_client.get(
            "/api/search/", params={"text": "very_rare_nonexistent_term"}
        )

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

        response = test_client.get(
            "/api/search/", params={"text": "癌症 breast cancer"}
        )

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
