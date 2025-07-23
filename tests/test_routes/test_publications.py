"""Tests for publication export route endpoints."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from pubtator_link.api.client import PubTator3Client
from pubtator_link.server_manager import UnifiedServerManager
from tests.fixtures.api_responses import MockPubTatorResponses

# Mock responses for publications testing
MOCK_PUBLICATION_EXPORT_RESPONSE = MockPubTatorResponses.publication_export_biocjson()


@pytest.fixture
def test_client():
    """Create test client."""
    manager = UnifiedServerManager()
    app = manager.create_app()
    return TestClient(app)


class TestPublicationRoutes:
    """Test publication export endpoints."""

    @patch.object(PubTator3Client, "export_publications")
    def test_export_publications_biocjson(self, mock_export, test_client):
        """Test publication export in biocjson format."""
        mock_export.return_value = MOCK_PUBLICATION_EXPORT_RESPONSE

        response = test_client.get(
            "/api/publications/export/biocjson",
            params={"pmids": "29355051", "full": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "biocjson"
        assert data["pmids"] == ["29355051"]
        assert data["full_text"] is False
        assert data["count"] == 1

    @patch.object(PubTator3Client, "export_publications")
    def test_export_publications_pubtator(self, mock_export, test_client):
        """Test publication export in pubtator format."""
        mock_export.return_value = {
            "content": (
                "29355051|t|BRCA1 mutations and breast cancer risk\n"
                "29355051|a|Abstract text here\n"
                "32511357|t|Second article title\n"
                "32511357|a|Second abstract"
            )
        }

        response = test_client.get(
            "/api/publications/export/pubtator", params={"pmids": "29355051,32511357"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "pubtator"
        assert data["pmids"] == ["29355051", "32511357"]
        # 2 PMIDs x 2 sections (title + abstract) = 4 documents
        assert data["count"] == 4

    def test_export_publications_invalid_format(self, test_client):
        """Test publication export with invalid format."""
        response = test_client.get("/api/publications/export/invalid", params={"pmids": "29355051"})

        assert response.status_code == 400
        data = response.json()
        assert "Invalid format" in data["detail"]

    def test_export_publications_full_text_pubtator_error(self, test_client):
        """Test that full text is not allowed with pubtator format."""
        response = test_client.get(
            "/api/publications/export/pubtator",
            params={"pmids": "29355051", "full": True},
        )

        assert response.status_code == 400
        data = response.json()
        assert "Full text is not supported for pubtator format" in data["detail"]

    @patch.object(PubTator3Client, "export_pmc_publications")
    def test_export_pmc_publications(self, mock_export, test_client):
        """Test PMC publication export."""
        mock_export.return_value = MOCK_PUBLICATION_EXPORT_RESPONSE

        response = test_client.get(
            "/api/publications/pmc_export/biocxml",
            params={"pmcids": "PMC7696669,PMC8869656"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "biocxml"
        assert data["pmcids"] == ["PMC7696669", "PMC8869656"]
        assert data["full_text"] is True  # PMC always includes full text
        assert data["count"] == 2

    def test_export_pmc_publications_invalid_format(self, test_client):
        """Test PMC export with unsupported format."""
        response = test_client.get(
            "/api/publications/pmc_export/pubtator", params={"pmcids": "PMC7696669"}
        )

        assert response.status_code == 400
        data = response.json()
        assert "PMC export only supports" in data["detail"]

    @patch.object(PubTator3Client, "export_publications")
    def test_export_publications_multiple_pmids(self, mock_export, test_client):
        """Test publication export with multiple PMIDs."""
        mock_export.return_value = MOCK_PUBLICATION_EXPORT_RESPONSE

        response = test_client.get(
            "/api/publications/export/biocjson",
            params={"pmids": "29355051,32511357,34170578", "full": True},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "biocjson"
        assert len(data["pmids"]) == 3
        assert data["full_text"] is True

    def test_export_publications_missing_pmids(self, test_client):
        """Test publication export without PMIDs parameter."""
        response = test_client.get("/api/publications/export/biocjson")

        assert response.status_code == 422  # Validation error

    def test_export_publications_empty_pmids(self, test_client):
        """Test publication export with empty PMIDs parameter."""
        response = test_client.get("/api/publications/export/biocjson", params={"pmids": ""})

        assert response.status_code == 400  # ValueError converted to 400

    @patch.object(PubTator3Client, "export_publications")
    def test_export_publications_biocxml_format(self, mock_export, test_client):
        """Test publication export in biocxml format."""
        mock_export.return_value = MockPubTatorResponses.publication_export_biocxml()

        response = test_client.get(
            "/api/publications/export/biocxml",
            params={"pmids": "29355051", "full": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "biocxml"
        assert data["pmids"] == ["29355051"]
        assert data["full_text"] is False

    @patch.object(PubTator3Client, "export_pmc_publications")
    def test_export_pmc_publications_biocjson(self, mock_export, test_client):
        """Test PMC publication export in biocjson format."""
        mock_export.return_value = MockPubTatorResponses.pmc_export_response()

        response = test_client.get(
            "/api/publications/pmc_export/biocjson",
            params={"pmcids": "PMC7696669"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "biocjson"
        assert data["pmcids"] == ["PMC7696669"]
        assert data["full_text"] is True

    def test_export_pmc_publications_missing_pmcids(self, test_client):
        """Test PMC export without PMCIDs parameter."""
        response = test_client.get("/api/publications/pmc_export/biocjson")

        assert response.status_code == 422  # Validation error

    def test_export_pmc_publications_invalid_pmcid_format(self, test_client):
        """Test PMC export with invalid PMC ID format."""
        response = test_client.get(
            "/api/publications/pmc_export/biocjson",
            params={"pmcids": "invalid_pmc_id"},
        )

        assert response.status_code == 400
        data = response.json()
        assert (
            "Invalid PMCID format: invalid_pmc_id. PMCIDs must start with 'PMC' followed by digits."
            in data["detail"]
        )
