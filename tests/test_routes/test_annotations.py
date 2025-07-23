"""Tests for text annotation route endpoints."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from pubtator_link.api.client import PubTator3Client
from pubtator_link.server_manager import UnifiedServerManager

# Mock responses based on actual API responses
MOCK_TEXT_ANNOTATION_SUBMIT_RESPONSE = "0DA64A2FE4D635D5820C"

MOCK_TEXT_ANNOTATION_RESULTS_RESPONSE = {
    "status": "completed",
    "original_text": "The ESR1 gene mutations and breast cancer risk.",
    "bioconcept": "Gene",
    "annotations": [
        {
            "start": 4,
            "end": 8,
            "text": "ESR1",
            "entity_id": "@GENE_2099",
            "entity_type": "Gene",
            "confidence": 0.95,
        }
    ],
    "processing_time": 12.5,
}


@pytest.fixture
def test_client():
    """Create test client."""
    manager = UnifiedServerManager()
    app = manager.create_app()
    return TestClient(app)


class TestAnnotationRoutes:
    """Test text annotation endpoints."""

    @patch.object(PubTator3Client, "submit_text_annotation")
    def test_submit_text_annotation_basic(self, mock_submit, test_client):
        """Test basic text annotation submission."""
        mock_submit.return_value = MOCK_TEXT_ANNOTATION_SUBMIT_RESPONSE

        response = test_client.post(
            "/api/annotations/submit",
            params={
                "text": "The ESR1 gene mutations and breast cancer risk.",
                "bioconcepts": "Gene,Disease",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "session_id" in data
        assert data["status"] == "submitted"
        assert "Gene" in data["bioconcepts"]
        assert "Disease" in data["bioconcepts"]

    @patch.object(PubTator3Client, "submit_text_annotation")
    def test_submit_text_annotation_all_concepts(self, mock_submit, test_client):
        """Test text annotation with all bioconcepts."""
        mock_submit.return_value = MOCK_TEXT_ANNOTATION_SUBMIT_RESPONSE

        response = test_client.post(
            "/api/annotations/submit",
            params={"text": "Test text", "bioconcepts": "all"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["bioconcepts"]) > 1  # Should include all concept types

    def test_submit_text_annotation_invalid_bioconcept(self, test_client):
        """Test text annotation with invalid bioconcept."""
        response = test_client.post(
            "/api/annotations/submit",
            params={"text": "Test text", "bioconcepts": "InvalidConcept"},
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid bioconcept" in data["detail"]

    @patch.object(PubTator3Client, "retrieve_text_annotation")
    def test_get_annotation_results(self, mock_get_results, test_client):
        """Test retrieving annotation results."""
        mock_get_results.return_value = MOCK_TEXT_ANNOTATION_RESULTS_RESPONSE

        response = test_client.get("/api/annotations/results/0DA64A2FE4D635D5820C")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["session_id"] == "0DA64A2FE4D635D5820C"
        assert data["status"] == "completed"
