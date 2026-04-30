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

    @staticmethod
    def _annotation_result(status: str) -> dict[str, object]:
        result: dict[str, object] = {
            "status": status,
            "original_text": "BRCA1 mutations increase breast cancer risk",
            "bioconcept": "Gene",
        }
        if status == "failed":
            result["error"] = "upstream processing failed"
        return result

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

    def test_submit_text_annotation_rejects_blank_text(self, test_client):
        """Test text annotation rejects empty text."""
        response = test_client.post(
            "/api/annotations/submit",
            params={"text": "   ", "bioconcepts": "Gene"},
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "Text is required and cannot be empty"

    def test_submit_text_annotation_rejects_text_over_limit(self, test_client):
        """Test text annotation rejects text over the public limit."""
        response = test_client.post(
            "/api/annotations/submit",
            params={"text": "x" * 10001, "bioconcepts": "Gene"},
        )

        assert response.status_code == 413
        assert "10,000 characters" in response.json()["detail"]

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

    @pytest.mark.parametrize("status", ["submitted", "processing"])
    @patch.object(PubTator3Client, "retrieve_text_annotation")
    def test_get_annotation_results_reports_in_progress_status(
        self,
        mock_get_results,
        test_client,
        status,
    ):
        """Test in-progress annotation statuses return 202 details."""
        mock_get_results.return_value = self._annotation_result(status)

        response = test_client.get("/api/annotations/results/0DA64A2FE4D635D5820C")

        assert response.status_code == 202
        detail = response.json()["detail"]
        assert detail["success"] is True
        assert detail["status"] == status
        assert detail["message"] == "Processing in progress. Please try again in a few moments."

    @patch.object(PubTator3Client, "retrieve_text_annotation")
    def test_get_annotation_results_reports_failed_status(self, mock_get_results, test_client):
        """Test failed annotation status returns an explicit server error."""
        mock_get_results.return_value = self._annotation_result("failed")

        response = test_client.get("/api/annotations/results/0DA64A2FE4D635D5820C")

        assert response.status_code == 500
        assert "upstream processing failed" in response.json()["detail"]

    @patch.object(PubTator3Client, "retrieve_text_annotation")
    def test_get_annotation_results_reports_expired_status(self, mock_get_results, test_client):
        """Test expired annotation status returns not found."""
        mock_get_results.return_value = self._annotation_result("expired")

        response = test_client.get("/api/annotations/results/0DA64A2FE4D635D5820C")

        assert response.status_code == 404
        assert "has expired" in response.json()["detail"]

    @patch.object(PubTator3Client, "retrieve_text_annotation")
    def test_get_annotation_results_reports_unknown_status(self, mock_get_results, test_client):
        """Test unknown annotation status returns an explicit server error."""
        mock_get_results.return_value = self._annotation_result("queued_elsewhere")

        response = test_client.get("/api/annotations/results/0DA64A2FE4D635D5820C")

        assert response.status_code == 500
        assert "Unknown processing status: queued_elsewhere" in response.json()["detail"]
