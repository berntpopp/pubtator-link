"""Test configuration and shared fixtures for PubTator-Link tests."""

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from pubtator_link.api.client import PubTator3Client
from pubtator_link.config import settings
from pubtator_link.server_manager import UnifiedServerManager
from pubtator_link.services.publication_service import PublicationService


def _reset_async_lru_method_cache(method: object) -> None:
    """Clear async-lru method cache and test loop metadata.

    async-lru stores the first event loop seen by a decorated method wrapper.
    pytest-asyncio uses function-scoped loops, so tests must reset this metadata
    in addition to cache entries to avoid cross-loop warnings.
    """
    method.cache_clear()
    wrapper = method._LRUCacheWrapperInstanceMethod__wrapper
    wrapper._LRUCacheWrapper__first_loop = None
    wrapper._LRUCacheWrapper__warned_loop_reset = False


@pytest.fixture(autouse=True)
def clear_publication_service_method_caches() -> None:
    """Prevent async-lru method caches from leaking across test event loops."""
    _reset_async_lru_method_cache(PublicationService.export_publications)
    _reset_async_lru_method_cache(PublicationService.export_pmc_publications)
    _reset_async_lru_method_cache(PublicationService.search_publications)


@pytest.fixture
def mock_logger():
    """Mock logger for testing."""
    logger = Mock()
    logger.info = Mock()
    logger.error = Mock()
    logger.warning = Mock()
    logger.debug = Mock()
    return logger


@pytest.fixture
def mock_pubtator_client():
    """Mock PubTator3Client for testing."""
    client = AsyncMock(spec=PubTator3Client)

    # Configure default return values
    client.export_publications = AsyncMock()
    client.export_pmc_publications = AsyncMock()
    client.autocomplete_entity = AsyncMock()
    client.search_publications = AsyncMock()
    client.find_relations = AsyncMock()
    client.submit_text_annotation = AsyncMock()
    client.retrieve_text_annotation = AsyncMock()
    client.get_annotation_results = AsyncMock()

    return client


@pytest.fixture
def mock_publication_service(mock_pubtator_client, mock_logger):
    """Mock PublicationService for testing."""
    service = Mock(spec=PublicationService)
    service.client = mock_pubtator_client
    service.logger = mock_logger

    # Configure async methods
    service.export_publications_list = AsyncMock()
    service.export_pmc_publications_list = AsyncMock()
    service.search_publications = AsyncMock()
    service.clear_cache = AsyncMock()
    service.get_cache_stats = Mock()
    service.get_supported_formats = Mock()

    return service


@pytest.fixture
def app():
    """Create FastAPI application instance for testing."""
    manager = UnifiedServerManager()
    app = manager.create_app()
    return app


@pytest.fixture
def test_client(app):
    """Create TestClient for FastAPI application."""
    return TestClient(app)


@pytest.fixture
async def async_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Create async HTTP client for testing."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def sample_pmids() -> list[str]:
    """Sample PMIDs for testing."""
    return ["29355051", "32511357", "34170578"]


@pytest.fixture
def sample_pmcids() -> list[str]:
    """Sample PMC IDs for testing."""
    return ["PMC7696669", "PMC8869656", "PMC9123456"]


@pytest.fixture
def sample_export_response() -> dict[str, Any]:
    """Sample publication export response."""
    return {
        "PubTator3": [
            {
                "_id": "29355051|None",
                "id": "29355051",
                "infons": {},
                "passages": [
                    {
                        "infons": {
                            "journal": "Integr Cancer Ther. 2018 Sep;17(3):860-866.",
                            "year": "2018",
                            "type": "title",
                        },
                        "offset": 0,
                        "text": "Fraction From Lycium barbarum Polysaccharides.",
                        "sentences": [],
                        "annotations": [
                            {
                                "id": "5",
                                "infons": {
                                    "identifier": "112863",
                                    "type": "Species",
                                    "valid": True,
                                },
                                "text": "Lycium barbarum",
                                "locations": [{"offset": 14, "length": 15}],
                            }
                        ],
                        "relations": [],
                    }
                ],
                "relations": [],
                "pmid": 29355051,
                "pmcid": None,
                "meta": {},
                "date": "2018-09-01T00:00:00Z",
                "journal": "Integr Cancer Ther",
                "authors": ["Deng X", "Luo S"],
                "relations_display": [],
            }
        ]
    }


@pytest.fixture
def sample_autocomplete_response() -> list[dict[str, Any]]:
    """Sample entity autocomplete response."""
    return [
        {
            "_id": "@DISEASE_Neoplasms",
            "biotype": "disease",
            "db_id": "D009369",
            "db": "ncbi_mesh",
            "name": "Neoplasms",
            "match": "Matched on synonyms <m>Cancer</m>",
        },
        {
            "_id": "@DISEASE_Breast_Neoplasms",
            "biotype": "disease",
            "db_id": "D001943",
            "db": "ncbi_mesh",
            "name": "Breast Neoplasms",
            "match": "Matched on synonyms <m>Cancer, Mammary</m>",
        },
    ]


@pytest.fixture
def sample_search_response() -> dict[str, Any]:
    """Sample publication search response."""
    return {
        "results": [
            {
                "_id": "37711410",
                "pmid": 37711410,
                "title": "Remdesivir.",
                "journal": "Hosp Pharm",
                "authors": ["Levien TL", "Baker DE"],
                "date": "2023-10-01T00:00:00Z",
                "doi": "10.1177/0018578721999804",
                "score": 266.66373,
                "text_hl": "@<m>CHEMICAL_remdesivir</m> @CHEMICAL_MESH:C000606551 @@@Remdesivir@@@.",
            },
            {
                "_id": "37061276",
                "pmid": 37061276,
                "pmcid": "PMC9910426",
                "title": "Remdesivir",
                "journal": "Profiles Drug Subst Excip Relat Methodol",
                "authors": ["Bakheit AH", "Darwish H"],
                "date": "2023-01-01T00:00:00Z",
                "score": 265.77936,
                "text_hl": "@<m>CHEMICAL_remdesivir</m> @CHEMICAL_MESH:C000606551 @@@Remdesivir@@@",
            },
        ],
        "total": 150,
        "per_page": 20,
    }


@pytest.fixture
def sample_relations_response() -> list[dict[str, Any]]:
    """Sample entity relations response."""
    return [
        {
            "type": "treat",
            "source": "@CHEMICAL_remdesivir",
            "target": "@DISEASE_COVID_19",
            "publications": 2155,
        },
        {
            "type": "treat",
            "source": "@CHEMICAL_remdesivir",
            "target": "@DISEASE_Coronavirus_Infections",
            "publications": 94,
        },
    ]


@pytest.fixture
def sample_text_annotation_submit_response() -> str:
    """Sample text annotation submit response."""
    return "0DA64A2FE4D635D5820C"


@pytest.fixture
def sample_text_annotation_results_response() -> dict[str, Any]:
    """Sample text annotation results response."""
    return {
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
def mock_rate_limiter():
    """Mock rate limiter for testing."""
    with patch("pubtator_link.api.client.AsyncLimiter") as mock_limiter:
        limiter_instance = AsyncMock()
        mock_limiter.return_value = limiter_instance
        yield limiter_instance


@pytest.fixture(autouse=True)
def override_settings():
    """Override settings for testing."""
    original_values = {}
    test_settings = {
        "log_level": "DEBUG",
        "cache_ttl": 60,  # Short TTL for testing
        "rate_limit": 10,  # Higher rate limit for testing
        "pubtator_base_url": "https://test.pubtator3.org",
    }

    # Store original values and set test values
    for key, value in test_settings.items():
        if hasattr(settings, key):
            original_values[key] = getattr(settings, key)
            setattr(settings, key, value)

    yield

    # Restore original values
    for key, value in original_values.items():
        setattr(settings, key, value)


# Error fixtures for testing error handling
@pytest.fixture
def api_error():
    """Sample API error for testing."""
    return {
        "error": "Invalid request",
        "message": "The provided PMIDs are not valid",
        "status": 400,
    }


@pytest.fixture
def rate_limit_error():
    """Sample rate limit error for testing."""
    return {
        "error": "Rate limit exceeded",
        "message": "Too many requests. Please wait before trying again.",
        "status": 429,
    }


# Test data fixtures
@pytest.fixture
def valid_bioconcepts() -> list[str]:
    """Return valid bioconcept types for testing."""
    return ["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine"]


@pytest.fixture
def valid_export_formats() -> list[str]:
    """Return valid export formats for testing."""
    return ["biocjson", "biocxml", "pubtator"]


@pytest.fixture
def valid_relation_types() -> list[str]:
    """Return valid relation types for testing."""
    return [
        "treat",
        "cause",
        "cotreat",
        "convert",
        "compare",
        "interact",
        "associate",
        "positive_correlate",
        "negative_correlate",
        "prevent",
        "inhibit",
        "stimulate",
        "drug_interact",
    ]


# Performance test fixtures
@pytest.fixture
def large_pmid_list() -> list[str]:
    """Large list of PMIDs for performance testing."""
    return [str(i) for i in range(30000000, 30000100)]  # 100 PMIDs


@pytest.fixture
def concurrent_requests():
    """Return configuration for concurrent request testing."""
    return {
        "concurrent_users": 10,
        "requests_per_user": 5,
        "max_response_time": 5.0,  # seconds
    }
