"""Comprehensive tests for service layer classes."""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from typing import Dict, List, Any

from pubtator_link.services.publication_service import PublicationService
from pubtator_link.api.client import PubTator3Client, PubTatorAPIError
from pubtator_link.models.responses import (
    PublicationExportResponse,
    PMCExportResponse,
    SearchResponse,
)
from tests.fixtures.api_responses import MockPubTatorResponses


class TestPublicationService:
    """Test publication service functionality."""

    @pytest.fixture
    def mock_client(self):
        """Create mock PubTator3 client."""
        client = Mock(spec=PubTator3Client)
        client.export_publications = AsyncMock()
        client.export_pmc_publications = AsyncMock()
        client.search_publications = AsyncMock()
        return client

    @pytest.fixture
    def publication_service(self, mock_client):
        """Create publication service with mock client."""
        return PublicationService(client=mock_client)

    @pytest.mark.asyncio
    async def test_export_publications_biocjson(self, publication_service, mock_client):
        """Test publication export in biocjson format."""
        mock_response = MockPubTatorResponses.publication_export_biocjson()
        mock_client.export_publications.return_value = mock_response

        result = await publication_service.export_publications(
            pmids_str="29355051", format="biocjson", full=False
        )

        assert isinstance(result, PublicationExportResponse)
        assert result.format == "biocjson"
        assert result.pmids == ["29355051"]
        assert result.full_text is False
        assert result.count >= 1
        assert "documents" in result.export_data

        mock_client.export_publications.assert_called_once_with(
            pmids=["29355051"], format="biocjson", full=False
        )

    @pytest.mark.asyncio
    async def test_export_publications_pubtator(self, publication_service, mock_client):
        """Test publication export in pubtator format."""
        mock_response = MockPubTatorResponses.publication_export_pubtator()
        mock_client.export_publications.return_value = mock_response

        result = await publication_service.export_publications(
            pmids_str="29355051,32511357", format="pubtator", full=False
        )

        assert isinstance(result, PublicationExportResponse)
        assert result.format == "pubtator"
        assert result.pmids == ["29355051", "32511357"]
        assert result.count >= 1

        mock_client.export_publications.assert_called_once_with(
            pmids=["29355051", "32511357"], format="pubtator", full=False
        )

    @pytest.mark.asyncio
    async def test_export_publications_biocxml(self, publication_service, mock_client):
        """Test publication export in biocxml format."""
        mock_response = MockPubTatorResponses.publication_export_biocxml()
        mock_client.export_publications.return_value = mock_response

        result = await publication_service.export_publications(
            pmids_str="29355051", format="biocxml", full=True
        )

        assert isinstance(result, PublicationExportResponse)
        assert result.format == "biocxml"
        assert result.full_text is True
        assert result.count >= 1

    @pytest.mark.asyncio
    async def test_export_publications_api_error(
        self, publication_service, mock_client
    ):
        """Test publication export with API error."""
        mock_client.export_publications.side_effect = PubTatorAPIError(
            "API Error", status_code=503
        )

        with pytest.raises(PubTatorAPIError):
            await publication_service.export_publications(
                pmids_str="29355051", format="biocjson"
            )

    @pytest.mark.asyncio
    async def test_export_publications_list_interface(
        self, publication_service, mock_client
    ):
        """Test publication export with list interface."""
        mock_response = MockPubTatorResponses.publication_export_biocjson()
        mock_client.export_publications.return_value = mock_response

        result = await publication_service.export_publications_list(
            pmids=["29355051", "32511357"], format="biocjson", full=False
        )

        assert isinstance(result, PublicationExportResponse)
        assert result.pmids == ["29355051", "32511357"]

        mock_client.export_publications.assert_called_once_with(
            pmids=["29355051", "32511357"], format="biocjson", full=False
        )

    @pytest.mark.asyncio
    async def test_export_pmc_publications_biocjson(
        self, publication_service, mock_client
    ):
        """Test PMC publication export in biocjson format."""
        mock_response = MockPubTatorResponses.pmc_export_response()
        mock_client.export_pmc_publications.return_value = mock_response

        result = await publication_service.export_pmc_publications(
            pmcids_str="PMC7696669", format="biocjson"
        )

        assert isinstance(result, PMCExportResponse)
        assert result.format == "biocjson"
        assert result.pmcids == ["PMC7696669"]
        assert len(result.documents) >= 0

        mock_client.export_pmc_publications.assert_called_once_with(
            pmcids=["PMC7696669"], format="biocjson"
        )

    @pytest.mark.asyncio
    async def test_export_pmc_publications_list_interface(
        self, publication_service, mock_client
    ):
        """Test PMC export with list interface."""
        mock_response = MockPubTatorResponses.pmc_export_response()
        mock_client.export_pmc_publications.return_value = mock_response

        result = await publication_service.export_pmc_publications_list(
            pmcids=["PMC7696669", "PMC8869656"], format="biocxml"
        )

        assert isinstance(result, PMCExportResponse)
        assert result.pmcids == ["PMC7696669", "PMC8869656"]

    @pytest.mark.asyncio
    async def test_export_pmc_publications_api_error(
        self, publication_service, mock_client
    ):
        """Test PMC export with API error."""
        mock_client.export_pmc_publications.side_effect = PubTatorAPIError(
            "PMC API Error", status_code=404
        )

        with pytest.raises(PubTatorAPIError):
            await publication_service.export_pmc_publications(
                pmcids_str="PMC7696669", format="biocjson"
            )

    @pytest.mark.asyncio
    async def test_search_publications_basic(self, publication_service, mock_client):
        """Test basic publication search."""
        mock_response = MockPubTatorResponses.search_publications_response()
        mock_client.search_publications.return_value = mock_response

        result = await publication_service.search_publications(
            text="breast cancer", page=1
        )

        assert isinstance(result, SearchResponse)
        assert result.query == "breast cancer"
        assert result.page == 1
        assert result.per_page == 20
        assert result.total_results == 150
        assert result.total_pages == 8  # ceil(150/20)
        assert len(result.results) == 3
        assert result.success is True

        mock_client.search_publications.assert_called_once_with(
            text="breast cancer", page=1
        )

    @pytest.mark.asyncio
    async def test_search_publications_entity_query(
        self, publication_service, mock_client
    ):
        """Test publication search with entity ID."""
        mock_response = MockPubTatorResponses.search_publications_response()
        mock_client.search_publications.return_value = mock_response

        result = await publication_service.search_publications(
            text="@CHEMICAL_remdesivir", page=1
        )

        assert result.query == "@CHEMICAL_remdesivir"
        assert "37711410" in str(result.results[0].pmid)

    @pytest.mark.asyncio
    async def test_search_publications_boolean_query(
        self, publication_service, mock_client
    ):
        """Test publication search with boolean operators."""
        mock_response = MockPubTatorResponses.search_publications_response()
        mock_client.search_publications.return_value = mock_response

        result = await publication_service.search_publications(
            text="@CHEMICAL_Doxorubicin AND @DISEASE_Neoplasms", page=1
        )

        assert "AND" in result.query
        assert result.success is True

    @pytest.mark.asyncio
    async def test_search_publications_no_results(
        self, publication_service, mock_client
    ):
        """Test publication search with no results."""
        empty_response = {"results": [], "total": 0, "per_page": 20}
        mock_client.search_publications.return_value = empty_response

        result = await publication_service.search_publications(
            text="nonexistent_term", page=1
        )

        assert result.total_results == 0
        assert len(result.results) == 0
        assert result.total_pages == 0

    @pytest.mark.asyncio
    async def test_search_publications_api_error(
        self, publication_service, mock_client
    ):
        """Test publication search with API error."""
        mock_client.search_publications.side_effect = PubTatorAPIError(
            "Search API Error", status_code=503
        )

        with pytest.raises(PubTatorAPIError):
            await publication_service.search_publications(text="cancer", page=1)

    @pytest.mark.asyncio
    async def test_caching_behavior(self, publication_service, mock_client):
        """Test that caching works correctly."""
        mock_response = MockPubTatorResponses.publication_export_biocjson()
        mock_client.export_publications.return_value = mock_response

        # First call
        result1 = await publication_service.export_publications(
            pmids_str="29355051", format="biocjson"
        )

        # Second call with same parameters should use cache
        result2 = await publication_service.export_publications(
            pmids_str="29355051", format="biocjson"
        )

        assert result1.pmids == result2.pmids
        assert result1.format == result2.format
        # Client should only be called once due to caching
        mock_client.export_publications.assert_called_once()

    @pytest.mark.asyncio
    async def test_pmid_parsing(self, publication_service, mock_client):
        """Test PMID string parsing logic."""
        mock_response = MockPubTatorResponses.publication_export_biocjson()
        mock_client.export_publications.return_value = mock_response

        # Test with comma-separated PMIDs and whitespace
        result = await publication_service.export_publications(
            pmids_str="29355051, 32511357 , 12345678", format="biocjson"
        )

        expected_pmids = ["29355051", "32511357", "12345678"]
        mock_client.export_publications.assert_called_with(
            pmids=expected_pmids, format="biocjson", full=False
        )

    @pytest.mark.asyncio
    async def test_pmcid_parsing(self, publication_service, mock_client):
        """Test PMCID string parsing logic."""
        mock_response = MockPubTatorResponses.pmc_export_response()
        mock_client.export_pmc_publications.return_value = mock_response

        # Test with comma-separated PMCIDs and whitespace
        result = await publication_service.export_pmc_publications(
            pmcids_str="PMC7696669, PMC8869656 ", format="biocjson"
        )

        expected_pmcids = ["PMC7696669", "PMC8869656"]
        mock_client.export_pmc_publications.assert_called_with(
            pmcids=expected_pmcids, format="biocjson"
        )

    @pytest.mark.asyncio
    async def test_logging_integration(self, mock_client):
        """Test service logging integration."""
        mock_logger = Mock()
        service = PublicationService(client=mock_client, logger=mock_logger)

        mock_response = MockPubTatorResponses.publication_export_biocjson()
        mock_client.export_publications.return_value = mock_response

        await service.export_publications(pmids_str="29355051", format="biocjson")

        # Verify logger was provided to service
        assert service.logger == mock_logger

    @pytest.mark.asyncio
    async def test_error_logging(self, mock_client):
        """Test that API errors are logged properly."""
        mock_logger = Mock()
        service = PublicationService(client=mock_client, logger=mock_logger)

        mock_client.export_publications.side_effect = PubTatorAPIError(
            "Test Error", status_code=503
        )

        with pytest.raises(PubTatorAPIError):
            await service.export_publications(pmids_str="29355051", format="biocjson")

        # Verify error was logged
        mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_multiple_formats_supported(self, publication_service, mock_client):
        """Test that multiple export formats are supported."""
        formats_to_test = ["biocjson", "pubtator", "biocxml"]

        for format_name in formats_to_test:
            mock_response = getattr(
                MockPubTatorResponses, f"publication_export_{format_name}"
            )()
            mock_client.export_publications.return_value = mock_response

            result = await publication_service.export_publications(
                pmids_str="29355051", format=format_name
            )

            assert result.format == format_name
            mock_client.export_publications.reset_mock()

    @pytest.mark.asyncio
    async def test_search_result_structure(self, publication_service, mock_client):
        """Test search result structure and data mapping."""
        mock_response = MockPubTatorResponses.search_publications_response()
        mock_client.search_publications.return_value = mock_response

        result = await publication_service.search_publications(
            text="test query", page=1
        )

        # Check that results are properly structured
        assert len(result.results) == 3
        first_result = result.results[0]
        assert hasattr(first_result, "pmid")
        assert hasattr(first_result, "title")
        assert hasattr(first_result, "journal")
        assert hasattr(first_result, "authors")

    @pytest.mark.asyncio
    async def test_edge_case_empty_pmids_string(self, publication_service, mock_client):
        """Test handling of edge case with empty PMID strings."""
        mock_response = MockPubTatorResponses.publication_export_biocjson()
        mock_client.export_publications.return_value = mock_response

        # Test with string containing only commas and whitespace
        result = await publication_service.export_publications(
            pmids_str="29355051,  ,  , 32511357", format="biocjson"
        )

        # Should filter out empty strings
        expected_pmids = ["29355051", "32511357"]
        mock_client.export_publications.assert_called_with(
            pmids=expected_pmids, format="biocjson", full=False
        )
