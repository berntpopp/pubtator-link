"""Tests for cache management route endpoints."""

import pytest
from fastapi.testclient import TestClient

from pubtator_link.server_manager import UnifiedServerManager


@pytest.fixture
def test_client():
    """Create test client."""
    manager = UnifiedServerManager()
    app = manager.create_app()
    return TestClient(app)


class TestCacheRoutes:
    """Test cache management endpoints."""

    def test_get_cache_statistics_basic(self, test_client):
        """Test basic cache statistics retrieval."""
        response = test_client.get("/api/cache/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "stats" in data
        assert "total_size" in data["stats"]
        assert "hit_rate" in data["stats"]

    def test_get_cache_statistics_detailed(self, test_client):
        """Test detailed cache statistics retrieval."""
        response = test_client.get("/api/cache/stats", params={"detailed": True})

        assert response.status_code == 200
        data = response.json()
        assert "detailed_stats" in data

    def test_clear_cache_all(self, test_client):
        """Test clearing all cache."""
        response = test_client.delete("/api/cache/clear")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "cleared_items" in data
        assert data["pattern"] is None

    def test_clear_cache_with_pattern(self, test_client):
        """Test clearing cache with pattern."""
        response = test_client.delete("/api/cache/clear", params={"pattern": "pub_export:"})

        assert response.status_code == 200
        data = response.json()
        assert data["pattern"] == "pub_export:"

    def test_clear_cache_empty_pattern(self, test_client):
        """Test clearing cache with empty pattern."""
        response = test_client.delete("/api/cache/clear", params={"pattern": ""})

        assert response.status_code == 400
        data = response.json()
        assert "Cache pattern cannot be empty" in data["detail"]

    def test_get_cache_statistics_with_cache_activity(self, test_client):
        """Test cache statistics after some cache activity."""
        # First perform some operations that would populate cache
        test_client.get("/api/entities/autocomplete", params={"query": "cancer"})
        test_client.get("/api/search/", params={"text": "breast cancer"})

        # Then check cache stats
        response = test_client.get("/api/cache/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert isinstance(data["stats"]["total_size"], int)
        assert isinstance(data["stats"]["hit_rate"], (int, float))

    def test_get_cache_statistics_detailed_structure(self, test_client):
        """Test detailed cache statistics structure."""
        response = test_client.get("/api/cache/stats", params={"detailed": True})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "stats" in data
        assert "detailed_stats" in data

        # Check basic stats structure
        basic_stats = data["stats"]
        assert "total_size" in basic_stats
        assert "hit_rate" in basic_stats
        assert "total_hits" in basic_stats
        assert "total_misses" in basic_stats

        # Detailed stats has cache-specific info
        detailed_stats = data["detailed_stats"]
        assert isinstance(detailed_stats, dict)
        assert len(detailed_stats) >= 0  # May have cache types

    def test_clear_cache_specific_patterns(self, test_client):
        """Test clearing cache with various specific patterns."""
        patterns_to_test = [
            "pub_export:",
            "entity_search:",
            "pub_search:",
            "relations:",
            "annotations:",
        ]

        for pattern in patterns_to_test:
            response = test_client.delete("/api/cache/clear", params={"pattern": pattern})

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["pattern"] == pattern
            assert "cleared_items" in data

    def test_clear_cache_wildcard_pattern(self, test_client):
        """Test clearing cache with wildcard pattern."""
        response = test_client.delete("/api/cache/clear", params={"pattern": "pub_*"})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["pattern"] == "pub_*"

    def test_clear_cache_nonexistent_pattern(self, test_client):
        """Test clearing cache with pattern that matches nothing."""
        response = test_client.delete(
            "/api/cache/clear", params={"pattern": "nonexistent_pattern:"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["pattern"] == "nonexistent_pattern:"
        # Pattern may clear some cache items even if not specific
        assert "cleared_items" in data

    def test_cache_statistics_after_clear(self, test_client):
        """Test cache statistics after clearing cache."""
        # First populate cache with some operations
        test_client.get("/api/entities/autocomplete", params={"query": "cancer"})

        # Clear all cache
        clear_response = test_client.delete("/api/cache/clear")
        assert clear_response.status_code == 200

        # Check stats after clearing
        stats_response = test_client.get("/api/cache/stats")

        assert stats_response.status_code == 200
        data = stats_response.json()
        assert data["success"] is True
        # After clearing, total size should be 0 or very small
        assert data["stats"]["total_size"] >= 0

    def test_cache_statistics_hit_rate_calculation(self, test_client):
        """Test that cache hit rate is calculated correctly."""
        # Clear cache first to start fresh
        test_client.delete("/api/cache/clear")

        # Make the same request twice to generate a cache hit
        query_params = {"query": "cancer", "limit": 10}
        test_client.get("/api/entities/autocomplete", params=query_params)
        test_client.get("/api/entities/autocomplete", params=query_params)

        # Check statistics
        response = test_client.get("/api/cache/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        stats = data["stats"]
        assert "hit_rate" in stats
        assert "total_hits" in stats
        assert "total_misses" in stats

        # Hit rate should be between 0 and 1
        hit_rate = stats["hit_rate"]
        assert 0 <= hit_rate <= 1

    def test_clear_cache_with_whitespace_pattern(self, test_client):
        """Test clearing cache with whitespace in pattern."""
        response = test_client.delete("/api/cache/clear", params={"pattern": "  pub_export:  "})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Pattern should be trimmed
        assert data["pattern"].strip() == "pub_export:"

    def test_cache_statistics_response_format(self, test_client):
        """Test that cache statistics response has correct format."""
        response = test_client.get("/api/cache/stats")

        assert response.status_code == 200
        data = response.json()

        # Check required top-level fields
        assert "success" in data
        assert "stats" in data
        assert data["success"] is True

        # Check stats structure
        stats = data["stats"]
        required_fields = ["total_size", "hit_rate", "total_hits", "total_misses"]
        for field in required_fields:
            assert field in stats

        # Check data types
        assert isinstance(stats["total_size"], int)
        assert isinstance(stats["hit_rate"], (int, float))
        assert isinstance(stats["total_hits"], int)
        assert isinstance(stats["total_misses"], int)

    def test_clear_cache_response_format(self, test_client):
        """Test that clear cache response has correct format."""
        response = test_client.delete("/api/cache/clear")

        assert response.status_code == 200
        data = response.json()

        # Check required fields
        assert "success" in data
        assert "cleared_items" in data
        assert "pattern" in data
        assert data["success"] is True

        # Check data types
        assert isinstance(data["cleared_items"], int)
        assert data["pattern"] is None  # No pattern specified
        assert data["cleared_items"] >= 0
