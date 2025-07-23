"""Tests for entity autocomplete route endpoints."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from pubtator_link.api.client import PubTator3Client
from pubtator_link.server_manager import UnifiedServerManager
from tests.fixtures.api_responses import MockPubTatorResponses

# Mock response for entity testing
MOCK_ENTITY_AUTOCOMPLETE_RESPONSE = MockPubTatorResponses.entity_autocomplete_response()


@pytest.fixture
def test_client():
    """Create test client."""
    manager = UnifiedServerManager()
    app = manager.create_app()
    return TestClient(app)


class TestEntityRoutes:
    """Test entity autocomplete endpoints."""

    @patch.object(PubTator3Client, "autocomplete_entity")
    def test_search_entity_ids_basic(self, mock_autocomplete, test_client):
        """Test basic entity ID search."""
        mock_autocomplete.return_value = MOCK_ENTITY_AUTOCOMPLETE_RESPONSE

        response = test_client.get(
            "/api/entities/autocomplete", params={"query": "cancer", "limit": 10}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["query"] == "cancer"
        assert len(data["matches"]) == 4  # Updated to match fixture
        assert data["matches"][0]["identifier"] == "@DISEASE_Neoplasms"
        assert data["matches"][0]["name"] == "Neoplasms"
        assert data["matches"][0]["type"] == "disease"

    @patch.object(PubTator3Client, "autocomplete_entity")
    def test_search_entity_ids_with_concept_filter(self, mock_autocomplete, test_client):
        """Test entity search with concept type filter."""
        mock_autocomplete.return_value = MOCK_ENTITY_AUTOCOMPLETE_RESPONSE

        response = test_client.get(
            "/api/entities/autocomplete",
            params={"query": "cancer", "concept": "Disease", "limit": 5},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["concept_filter"] == "Disease"
        assert data["total_matches"] == 4  # Updated to match fixture

    def test_search_entity_ids_invalid_concept(self, test_client):
        """Test entity search with invalid concept type."""
        response = test_client.get(
            "/api/entities/autocomplete",
            params={"query": "cancer", "concept": "InvalidType"},
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid bioconcept" in data["detail"]

    @patch.object(PubTator3Client, "autocomplete_entity")
    def test_search_entity_ids_gene_query(self, mock_autocomplete, test_client):
        """Test entity search for genes."""
        gene_response = [
            {
                "_id": "@GENE_BRCA1",
                "biotype": "gene",
                "db_id": "672",
                "db": "ncbi_gene",
                "name": "BRCA1",
                "match": "Matched on symbol <m>BRCA1</m>",
            }
        ]
        mock_autocomplete.return_value = gene_response

        response = test_client.get(
            "/api/entities/autocomplete",
            params={"query": "BRCA1", "concept": "Gene", "limit": 10},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["concept_filter"] == "Gene"
        assert len(data["matches"]) == 1
        assert data["matches"][0]["identifier"] == "@GENE_BRCA1"
        assert data["matches"][0]["type"] == "gene"

    @patch.object(PubTator3Client, "autocomplete_entity")
    def test_search_entity_ids_chemical_query(self, mock_autocomplete, test_client):
        """Test entity search for chemicals."""
        chemical_response = [
            {
                "_id": "@CHEMICAL_Aspirin",
                "biotype": "chemical",
                "db_id": "D001241",
                "db": "ncbi_mesh",
                "name": "Aspirin",
                "match": "Matched on name <m>Aspirin</m>",
            }
        ]
        mock_autocomplete.return_value = chemical_response

        response = test_client.get(
            "/api/entities/autocomplete",
            params={"query": "aspirin", "concept": "Chemical"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["concept_filter"] == "Chemical"
        assert data["matches"][0]["identifier"] == "@CHEMICAL_Aspirin"
        assert data["matches"][0]["type"] == "chemical"

    def test_search_entity_ids_missing_query(self, test_client):
        """Test entity search without query parameter."""
        response = test_client.get("/api/entities/autocomplete")

        assert response.status_code == 422  # Validation error

    def test_search_entity_ids_empty_query(self, test_client):
        """Test entity search with empty query."""
        response = test_client.get("/api/entities/autocomplete", params={"query": ""})

        assert response.status_code == 422  # Validation error

    @patch.object(PubTator3Client, "autocomplete_entity")
    def test_search_entity_ids_default_limit(self, mock_autocomplete, test_client):
        """Test entity search with default limit."""
        mock_autocomplete.return_value = MOCK_ENTITY_AUTOCOMPLETE_RESPONSE

        response = test_client.get("/api/entities/autocomplete", params={"query": "cancer"})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["query"] == "cancer"

    @patch.object(PubTator3Client, "autocomplete_entity")
    def test_search_entity_ids_custom_limit(self, mock_autocomplete, test_client):
        """Test entity search with custom limit."""
        mock_autocomplete.return_value = MOCK_ENTITY_AUTOCOMPLETE_RESPONSE

        response = test_client.get(
            "/api/entities/autocomplete", params={"query": "cancer", "limit": 50}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["query"] == "cancer"

    def test_search_entity_ids_invalid_limit(self, test_client):
        """Test entity search with invalid limit."""
        response = test_client.get(
            "/api/entities/autocomplete", params={"query": "cancer", "limit": 0}
        )

        assert response.status_code == 422  # Validation error

    def test_search_entity_ids_limit_too_high(self, test_client):
        """Test entity search with limit exceeding maximum."""
        response = test_client.get(
            "/api/entities/autocomplete", params={"query": "cancer", "limit": 1000}
        )

        assert response.status_code == 422  # Validation error

    @patch.object(PubTator3Client, "autocomplete_entity")
    def test_search_entity_ids_no_results(self, mock_autocomplete, test_client):
        """Test entity search with no results."""
        mock_autocomplete.return_value = []

        response = test_client.get(
            "/api/entities/autocomplete", params={"query": "nonexistent_entity"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["matches"]) == 0
        assert data["total_matches"] == 0

    @patch.object(PubTator3Client, "autocomplete_entity")
    def test_search_entity_ids_with_api_error(self, mock_autocomplete, test_client):
        """Test entity search handling API errors."""
        from pubtator_link.api.client import PubTatorAPIError

        mock_autocomplete.side_effect = PubTatorAPIError("API Error", status_code=503)

        response = test_client.get("/api/entities/autocomplete", params={"query": "cancer"})

        # API errors get caught and converted to 500 status by dependencies.py
        assert response.status_code == 500

    @patch.object(PubTator3Client, "autocomplete_entity")
    def test_search_entity_ids_species_query(self, mock_autocomplete, test_client):
        """Test entity search for species."""
        species_response = [
            {
                "_id": "@SPECIES_Homo_sapiens",
                "biotype": "species",
                "db_id": "9606",
                "db": "ncbi_taxonomy",
                "name": "Homo sapiens",
                "match": "Matched on name <m>human</m>",
            }
        ]
        mock_autocomplete.return_value = species_response

        response = test_client.get(
            "/api/entities/autocomplete",
            params={"query": "human", "concept": "Species"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["concept_filter"] == "Species"
        assert data["matches"][0]["identifier"] == "@SPECIES_Homo_sapiens"
        assert data["matches"][0]["type"] == "species"

    def test_search_entity_ids_all_concept_types(self, test_client):
        """Test that all valid concept types are accepted."""
        valid_concepts = [
            "Gene",
            "Disease",
            "Chemical",
            "Species",
            "Variant",
            "CellLine",
        ]

        for concept in valid_concepts:
            response = test_client.get(
                "/api/entities/autocomplete",
                params={"query": "test", "concept": concept},
            )
            # Should not return validation error for valid concepts
            assert response.status_code != 400

    @patch.object(PubTator3Client, "autocomplete_entity")
    def test_search_entity_ids_unicode_query(self, mock_autocomplete, test_client):
        """Test entity search with unicode characters."""
        mock_autocomplete.return_value = []

        response = test_client.get("/api/entities/autocomplete", params={"query": "癌症"})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["query"] == "癌症"
