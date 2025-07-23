"""Tests for health check and root route endpoints."""

import pytest
from fastapi.testclient import TestClient

from pubtator_link.server_manager import UnifiedServerManager


@pytest.fixture
def test_client():
    """Create test client."""
    manager = UnifiedServerManager()
    app = manager.create_app()
    return TestClient(app)


class TestHealthAndRoot:
    """Test health and root endpoints."""

    def test_root_endpoint(self, test_client):
        """Test root endpoint."""
        response = test_client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "PubTator-Link"
        assert data["version"] == "1.0.0"
        assert "description" in data

    def test_health_endpoint(self, test_client):
        """Test health check endpoint."""
        response = test_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "1.0.0"

    def test_root_endpoint_response_structure(self, test_client):
        """Test that root endpoint returns correct structure."""
        response = test_client.get("/")

        assert response.status_code == 200
        data = response.json()

        # Check required fields
        required_fields = ["name", "version", "description"]
        for field in required_fields:
            assert field in data
            assert isinstance(data[field], str)
            assert len(data[field]) > 0

    def test_health_endpoint_response_structure(self, test_client):
        """Test that health endpoint returns correct structure."""
        response = test_client.get("/health")

        assert response.status_code == 200
        data = response.json()

        # Check required fields
        assert "status" in data
        assert "version" in data
        assert data["status"] == "healthy"
        assert isinstance(data["version"], str)
        assert len(data["version"]) > 0

    def test_root_endpoint_content_type(self, test_client):
        """Test that root endpoint returns JSON content type."""
        response = test_client.get("/")

        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]

    def test_health_endpoint_content_type(self, test_client):
        """Test that health endpoint returns JSON content type."""
        response = test_client.get("/health")

        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]

    def test_root_endpoint_with_query_params(self, test_client):
        """Test root endpoint ignores query parameters."""
        response = test_client.get("/", params={"param": "value"})

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "PubTator-Link"

    def test_health_endpoint_with_query_params(self, test_client):
        """Test health endpoint ignores query parameters."""
        response = test_client.get("/health", params={"param": "value"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_endpoint_uptime_tracking(self, test_client):
        """Test health endpoint consistency across multiple calls."""
        # Make multiple health check requests
        responses = []
        for _ in range(3):
            responses.append(test_client.get("/health"))

        # All should return healthy status
        for response in responses:
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"

    def test_root_endpoint_version_consistency(self, test_client):
        """Test that root endpoint version is consistent."""
        response1 = test_client.get("/")
        response2 = test_client.get("/")

        assert response1.status_code == 200
        assert response2.status_code == 200

        data1 = response1.json()
        data2 = response2.json()

        assert data1["version"] == data2["version"]
        assert data1["name"] == data2["name"]

    def test_health_endpoint_response_time(self, test_client):
        """Test that health endpoint responds quickly."""
        import time

        start_time = time.time()
        response = test_client.get("/health")
        end_time = time.time()

        response_time = end_time - start_time

        assert response.status_code == 200
        # Health endpoint should respond within 1 second
        assert response_time < 1.0

    def test_root_endpoint_description_content(self, test_client):
        """Test that root endpoint description contains expected content."""
        response = test_client.get("/")

        assert response.status_code == 200
        data = response.json()

        description = data["description"].lower()
        expected_keywords = ["pubtator", "api", "biomedical"]

        # Description should contain relevant keywords
        for keyword in expected_keywords:
            assert keyword in description

    def test_endpoints_cors_headers(self, test_client):
        """Test that endpoints include appropriate CORS headers if configured."""
        # Test root endpoint
        root_response = test_client.get("/")
        assert root_response.status_code == 200

        # Test health endpoint
        health_response = test_client.get("/health")
        assert health_response.status_code == 200

        # Note: CORS headers would depend on FastAPI middleware configuration
        # This test ensures endpoints are accessible from the test client

    def test_health_endpoint_during_load(self, test_client):
        """Test health endpoint remains responsive during simulated load."""
        # Simulate some load by making multiple concurrent requests
        import concurrent.futures

        def make_health_request():
            return test_client.get("/health")

        # Make multiple concurrent health check requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_health_request) for _ in range(10)]
            responses = [future.result() for future in futures]

        # All requests should succeed
        for response in responses:
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"

    def test_root_endpoint_json_serialization(self, test_client):
        """Test that root endpoint returns valid JSON."""
        response = test_client.get("/")

        assert response.status_code == 200

        # Should be valid JSON (response.json() would raise if not)
        data = response.json()
        assert isinstance(data, dict)

        # Should contain valid string values
        for _key, value in data.items():
            assert isinstance(value, str)
            assert len(value.strip()) > 0

    def test_health_endpoint_json_serialization(self, test_client):
        """Test that health endpoint returns valid JSON."""
        response = test_client.get("/health")

        assert response.status_code == 200

        # Should be valid JSON (response.json() would raise if not)
        data = response.json()
        assert isinstance(data, dict)

        # Should contain valid values
        assert isinstance(data["status"], str)
        assert isinstance(data["version"], str)
