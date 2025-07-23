"""Shared dependencies and dependency injection for FastAPI routes."""

import functools
import logging
from typing import Annotated, Any, Callable

from fastapi import Depends, HTTPException
from structlog.typing import FilteringBoundLogger

from ...api.client import PubTator3Client
from ...logging_config import configure_logging
from ...services.publication_service import PublicationService


logger = logging.getLogger(__name__)


# Global instances - initialized once per application lifecycle
_api_client: PubTator3Client | None = None
_publication_service: PublicationService | None = None
_logger: FilteringBoundLogger | None = None


async def get_logger() -> FilteringBoundLogger:
    """Get structured logger instance."""
    global _logger
    if _logger is None:
        _logger = configure_logging()
    return _logger


async def get_api_client() -> PubTator3Client:
    """Get PubTator3 API client instance."""
    global _api_client
    if _api_client is None:
        logger_instance = await get_logger()
        _api_client = PubTator3Client(logger=logger_instance)
    return _api_client


async def get_publication_service() -> PublicationService:
    """Get publication service instance."""
    global _publication_service
    if _publication_service is None:
        client = await get_api_client()
        logger_instance = await get_logger()
        _publication_service = PublicationService(client=client, logger=logger_instance)
    return _publication_service


# Type aliases for dependency injection
LoggerDep = Annotated[FilteringBoundLogger, Depends(get_logger)]
ClientDep = Annotated[PubTator3Client, Depends(get_api_client)]
PublicationServiceDep = Annotated[PublicationService, Depends(get_publication_service)]


def handle_api_errors(func: Callable) -> Callable:
    """Handle common API errors and convert to HTTP exceptions."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            # Re-raise HTTP exceptions as-is (from route-level error handling)
            raise
        except ValueError as e:
            # Client-side validation errors
            raise HTTPException(status_code=400, detail=str(e))
        except ConnectionError:
            # Network/connection errors
            raise HTTPException(
                status_code=503, detail="Service temporarily unavailable"
            )
        except TimeoutError:
            # Request timeout errors
            raise HTTPException(status_code=504, detail="Request timeout")
        except Exception as e:
            # Generic server errors
            logger.error(f"Unexpected error in {func.__name__}: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    return wrapper


def create_error_response(error: Exception, status_code: int) -> dict[str, Any]:
    """Create standardized error response."""
    return {
        "error": {
            "code": status_code,
            "message": str(error),
            "type": type(error).__name__,
        }
    }


def validate_pmids(pmids_str: str) -> list[str]:
    """Validate and parse comma-separated PMIDs."""
    if not pmids_str or pmids_str.strip() == "":
        raise ValueError("PMIDs parameter is required")

    pmids = [pmid.strip() for pmid in pmids_str.split(",") if pmid.strip()]

    if not pmids:
        raise ValueError("At least one PMID must be provided")

    # Validate PMID format (should be numeric)
    for pmid in pmids:
        if not pmid.isdigit():
            raise ValueError(f"Invalid PMID format: {pmid}. PMIDs must be numeric.")

    return pmids


def validate_pmcids(pmcids_str: str) -> list[str]:
    """Validate and parse comma-separated PMC IDs."""
    if not pmcids_str or pmcids_str.strip() == "":
        raise ValueError("PMCIDs parameter is required")

    pmcids = [pmcid.strip() for pmcid in pmcids_str.split(",") if pmcid.strip()]

    if not pmcids:
        raise ValueError("At least one PMCID must be provided")

    # Validate PMCID format (should start with PMC followed by digits)
    for pmcid in pmcids:
        if not pmcid.startswith("PMC") or not pmcid[3:].isdigit():
            raise ValueError(
                f"Invalid PMCID format: {pmcid}. PMCIDs must start with 'PMC' followed by digits."
            )

    return pmcids


def validate_entity_id(entity_id: str) -> str:
    """Validate entity ID format for PubTator3."""
    if not entity_id or not entity_id.startswith("@"):
        raise ValueError("Entity ID must start with '@' (e.g., @CHEMICAL_remdesivir)")

    if len(entity_id) < 5:  # Minimum: @A_B
        raise ValueError("Entity ID too short. Format: @CONCEPT_identifier")

    return entity_id


def validate_page_number(page: int) -> int:
    """Validate page number for pagination."""
    if page < 1:
        raise ValueError("Page number must be positive (starting from 1)")

    if page > 1000:  # Reasonable upper limit
        raise ValueError("Page number too large (maximum 1000)")

    return page


def validate_limit(limit: int, max_limit: int = 100) -> int:
    """Validate limit parameter for result count."""
    if limit < 1:
        raise ValueError("Limit must be positive")

    if limit > max_limit:
        raise ValueError(f"Limit too large (maximum {max_limit})")

    return limit


async def cleanup_dependencies():
    """Cleanup function for graceful shutdown."""
    global _api_client, _publication_service, _logger

    if _api_client:
        await _api_client.close()
        _api_client = None

    _publication_service = None
    _logger = None
