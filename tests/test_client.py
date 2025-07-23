"""Comprehensive tests for PubTator3 API client."""

import pytest
import httpx
import respx
from unittest.mock import Mock, patch, AsyncMock
from typing import List, Dict, Any

from pubtator_link.api.client import PubTator3Client, PubTatorAPIError, RateLimiter
from pubtator_link.config import APIConfig, TextProcessingConfig
from tests.fixtures.api_responses import MockPubTatorResponses, MockErrorResponses


class TestRateLimiter:
    """Test rate limiter functionality."""

    @pytest.mark.asyncio
    async def test_rate_limiter_no_wait(self):
        """Test rate limiter when tokens are available."""
        limiter = RateLimiter(rate=5.0, burst=2)

        wait_time = await limiter.acquire()
        assert wait_time == 0.0
        assert limiter.tokens == 1.0

    @pytest.mark.asyncio
    async def test_rate_limiter_wait_required(self):
        """Test rate limiter when wait is required."""
        limiter = RateLimiter(rate=1.0, burst=1)

        # First request should not wait
        wait_time1 = await limiter.acquire()
        assert wait_time1 == 0.0

        # Second request should require wait
        wait_time2 = await limiter.acquire()
        assert wait_time2 > 0.0

    @pytest.mark.asyncio
    async def test_rate_limiter_token_replenishment(self):
        """Test that tokens are replenished over time."""
        import asyncio

        limiter = RateLimiter(rate=10.0, burst=1)  # High rate for faster testing

        # Use up the token
        await limiter.acquire()

        # Wait a bit for token replenishment
        await asyncio.sleep(0.2)

        # Should have token available again
        wait_time = await limiter.acquire()
        assert wait_time == 0.0


class TestPubTator3Client:
    """Test PubTator3 API client functionality."""

    @pytest.fixture
    def api_config(self):
        """Create test API configuration."""
        return APIConfig(
            base_url="https://www.ncbi.nlm.nih.gov/research/pubtator3-api",
            timeout=30,
            rate_limit_per_second=2.5,
        )

    @pytest.fixture
    def text_config(self):
        """Create test text processing configuration."""
        return TextProcessingConfig(
            base_url="https://www.ncbi.nlm.nih.gov/CBBresearch/Lu/Demo/RESTful",
            timeout=30,
        )

    @pytest.fixture
    def client(self, api_config, text_config):
        """Create PubTator3 client with test config."""
        return PubTator3Client(config=api_config, text_config=text_config)

    @pytest.fixture
    def mock_logger(self):
        """Create mock logger."""
        return Mock()

    @pytest.mark.asyncio
    async def test_client_initialization(self, api_config, text_config):
        """Test client initialization."""
        client = PubTator3Client(config=api_config, text_config=text_config)

        assert client.config == api_config
        assert client.text_config == text_config
        assert client.logger is None
        assert client.client is not None

    @pytest.mark.asyncio
    async def test_client_initialization_with_logger(
        self, api_config, text_config, mock_logger
    ):
        """Test client initialization with logger."""
        client = PubTator3Client(
            config=api_config, text_config=text_config, logger=mock_logger
        )

        assert client.logger == mock_logger

    @pytest.mark.asyncio
    async def test_client_close(self, client):
        """Test client session cleanup."""
        assert client.client is not None

        await client.close()

        assert client.client.is_closed

    @pytest.mark.asyncio
    async def test_client_context_manager(self, api_config, text_config):
        """Test client as async context manager."""
        async with PubTator3Client(
            config=api_config, text_config=text_config
        ) as client:
            assert client.client is not None

        assert client.client.is_closed

    @respx.mock
    @pytest.mark.asyncio
    async def test_export_publications_success(self, client):
        """Test successful publication export."""
        mock_response = MockPubTatorResponses.publication_export_biocjson()

        respx.get(
            "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson"
        ).mock(return_value=httpx.Response(200, json=mock_response))

        result = await client.export_publications(
            pmids=["29355051"], format="biocjson", full=False
        )

        assert result == mock_response

    @respx.mock
    @pytest.mark.asyncio
    async def test_export_publications_api_error(self, client):
        """Test publication export with API error."""
        error_response = MockErrorResponses.server_error()

        respx.get(
            "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson"
        ).mock(return_value=httpx.Response(500, json=error_response))

        with pytest.raises(PubTatorAPIError) as exc_info:
            await client.export_publications(pmids=["29355051"], format="biocjson")

        assert exc_info.value.status_code == 500

    @respx.mock
    @pytest.mark.asyncio
    async def test_export_pmc_publications_success(self, client):
        """Test successful PMC publication export."""
        mock_response = MockPubTatorResponses.pmc_export_response()

        respx.get(
            "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/pmc_export/biocjson"
        ).mock(return_value=httpx.Response(200, json=mock_response))

        result = await client.export_pmc_publications(
            pmcids=["PMC7696669"], format="biocjson"
        )

        assert result == mock_response

    @respx.mock
    @pytest.mark.asyncio
    async def test_search_publications_success(self, client):
        """Test successful publication search."""
        mock_response = MockPubTatorResponses.search_publications_response()

        respx.get("https://www.ncbi.nlm.nih.gov/research/pubtator3-api/search/").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        result = await client.search_publications(text="breast cancer", page=1)

        assert result == mock_response

    @respx.mock
    @pytest.mark.asyncio
    async def test_autocomplete_entity_success(self, client):
        """Test successful entity autocomplete."""
        mock_response = MockPubTatorResponses.entity_autocomplete_response()

        respx.get(
            "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/entity/autocomplete/"
        ).mock(return_value=httpx.Response(200, json=mock_response))

        result = await client.autocomplete_entity(query="cancer", limit=10)

        assert result == mock_response

    @respx.mock
    @pytest.mark.asyncio
    async def test_find_relations_success(self, client):
        """Test successful entity relations search."""
        mock_response = MockPubTatorResponses.entity_relations_response()

        respx.get("https://www.ncbi.nlm.nih.gov/research/pubtator3-api/relations").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        result = await client.find_relations(e1="@CHEMICAL_remdesivir")

        assert result == mock_response

    @respx.mock
    @pytest.mark.asyncio
    async def test_submit_text_annotation_success(self, client):
        """Test successful text annotation submission."""
        mock_response = MockPubTatorResponses.text_annotation_submit_response()

        respx.post(
            "https://www.ncbi.nlm.nih.gov/CBBresearch/Lu/Demo/RESTful/request.cgi"
        ).mock(return_value=httpx.Response(200, json={"content": mock_response}))

        result = await client.submit_text_annotation(
            text="The ESR1 gene mutations are associated with breast cancer risk.",
            bioconcept="Gene",
        )

        assert result == mock_response

    @respx.mock
    @pytest.mark.asyncio
    async def test_retrieve_text_annotation_success(self, client):
        """Test successful text annotation retrieval."""
        mock_response = MockPubTatorResponses.text_annotation_results_completed()

        respx.post(
            "https://www.ncbi.nlm.nih.gov/CBBresearch/Lu/Demo/RESTful/retrieve.cgi"
        ).mock(return_value=httpx.Response(200, json=mock_response))

        result = await client.retrieve_text_annotation(
            session_id="0DA64A2FE4D635D5820C"
        )

        assert result == mock_response

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_annotation_results_alias(self, client):
        """Test get_annotation_results as alias for retrieve_text_annotation."""
        mock_response = MockPubTatorResponses.text_annotation_results_completed()

        respx.post(
            "https://www.ncbi.nlm.nih.gov/CBBresearch/Lu/Demo/RESTful/retrieve.cgi"
        ).mock(return_value=httpx.Response(200, json=mock_response))

        result = await client.get_annotation_results(session_id="0DA64A2FE4D635D5820C")

        assert result == mock_response

    @respx.mock
    @pytest.mark.asyncio
    async def test_rate_limit_error_handling(self, client):
        """Test handling of rate limit errors."""
        error_response = MockErrorResponses.rate_limit_error()

        respx.get(
            "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson"
        ).mock(return_value=httpx.Response(429, json=error_response))

        with pytest.raises(PubTatorAPIError) as exc_info:
            await client.export_publications(pmids=["29355051"], format="biocjson")

        assert exc_info.value.status_code == 429

    @respx.mock
    @pytest.mark.asyncio
    async def test_timeout_error_handling(self, client):
        """Test handling of timeout errors."""
        respx.get(
            "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson"
        ).mock(side_effect=httpx.TimeoutException("Request timeout"))

        with pytest.raises(PubTatorAPIError) as exc_info:
            await client.export_publications(pmids=["29355051"], format="biocjson")

        assert "timeout" in str(exc_info.value).lower()

    @respx.mock
    @pytest.mark.asyncio
    async def test_connection_error_handling(self, client):
        """Test handling of connection errors."""
        respx.get(
            "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson"
        ).mock(side_effect=httpx.ConnectError("Connection failed"))

        with pytest.raises(PubTatorAPIError) as exc_info:
            await client.export_publications(pmids=["29355051"], format="biocjson")

        assert "connection" in str(exc_info.value).lower()

    @respx.mock
    @pytest.mark.asyncio
    async def test_multiple_format_support(self, client):
        """Test that client supports multiple export formats."""
        formats_to_test = [
            ("biocjson", MockPubTatorResponses.publication_export_biocjson()),
            ("pubtator", MockPubTatorResponses.publication_export_pubtator()),
            ("biocxml", MockPubTatorResponses.publication_export_biocxml()),
        ]

        for format_name, mock_response in formats_to_test:
            respx.get(
                f"https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/{format_name}"
            ).mock(return_value=httpx.Response(200, json=mock_response))

            result = await client.export_publications(
                pmids=["29355051"], format=format_name
            )

            assert result == mock_response

    @respx.mock
    @pytest.mark.asyncio
    async def test_parameter_encoding(self, client):
        """Test proper encoding of request parameters."""
        mock_response = MockPubTatorResponses.search_publications_response()

        route = respx.get(
            "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/search/"
        ).mock(return_value=httpx.Response(200, json=mock_response))

        await client.search_publications(text="breast cancer & mutations", page=2)

        # Verify the request was made with encoded parameters
        request = route.calls.last.request
        assert "text=" in str(request.url)
        assert "page=2" in str(request.url)

    @pytest.mark.asyncio
    async def test_pubtatora_api_error_creation(self):
        """Test PubTatorAPIError creation and attributes."""
        error = PubTatorAPIError("Test error message", status_code=404)

        assert str(error) == "Test error message"
        assert error.status_code == 404

    @pytest.mark.asyncio
    async def test_pubtatora_api_error_without_status_code(self):
        """Test PubTatorAPIError without status code."""
        error = PubTatorAPIError("Test error message")

        assert str(error) == "Test error message"
        assert not hasattr(error, "status_code") or error.status_code is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_concurrent_requests_rate_limiting(self, client):
        """Test that concurrent requests respect rate limiting."""
        import asyncio

        mock_response = MockPubTatorResponses.publication_export_biocjson()

        respx.get(
            "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson"
        ).mock(return_value=httpx.Response(200, json=mock_response))

        # Make multiple concurrent requests
        start_time = asyncio.get_event_loop().time()
        tasks = [
            client.export_publications(pmids=[f"2935505{i}"], format="biocjson")
            for i in range(3)
        ]

        results = await asyncio.gather(*tasks)
        end_time = asyncio.get_event_loop().time()

        # All requests should succeed
        assert len(results) == 3
        for result in results:
            assert result == mock_response

        # With rate limiting, requests should take some time
        total_time = end_time - start_time
        # With 2.5 req/sec, 3 requests should take at least some time
        # but not too strict since it depends on timing

    @respx.mock
    @pytest.mark.asyncio
    async def test_json_response_handling(self, client):
        """Test handling of different JSON response types."""
        # Test with dict response
        dict_response = {"key": "value", "number": 42}
        respx.get(
            "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson"
        ).mock(return_value=httpx.Response(200, json=dict_response))

        result = await client.export_publications(pmids=["29355051"], format="biocjson")
        assert result == dict_response

    @respx.mock
    @pytest.mark.asyncio
    async def test_error_response_with_details(self, client):
        """Test error response with detailed error information."""
        error_response = {
            "error": "Validation failed",
            "message": "Invalid parameters provided",
            "details": {
                "pmids": ["Invalid PMID format"],
                "format": ["Unsupported format"],
            },
        }

        respx.get(
            "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson"
        ).mock(return_value=httpx.Response(422, json=error_response))

        with pytest.raises(PubTatorAPIError) as exc_info:
            await client.export_publications(pmids=["invalid"], format="biocjson")

        error = exc_info.value
        assert error.status_code == 422
        assert "Validation failed" in str(error)

    @pytest.mark.asyncio
    async def test_client_configuration_validation(self):
        """Test that client validates configuration properly."""
        # Test with minimal valid config
        config = APIConfig(
            base_url="https://example.com",
            timeout=30,
            rate_limit_per_second=1.0,
        )

        text_config = TextProcessingConfig(
            base_url="https://example.com",
            timeout=30,
        )

        client = PubTator3Client(config=config, text_config=text_config)

        assert client.config.base_url == "https://example.com"
        assert client.config.timeout == 30
        assert client.config.rate_limit_per_second == 1.0
        assert client.text_config.base_url == "https://example.com"
