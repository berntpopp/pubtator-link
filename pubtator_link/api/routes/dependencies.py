"""Shared dependencies and dependency injection for FastAPI routes."""

import functools
import logging
from collections.abc import Callable
from typing import Annotated, Any

import asyncpg
from fastapi import Depends, HTTPException
from structlog.typing import FilteringBoundLogger

from ...api.client import PubTator3Client
from ...config import review_rerag_config
from ...logging_config import configure_logging
from ...repositories.review_rerag import PostgresReviewReragRepository
from ...services.full_text_preparation import FullTextPreparationService
from ...services.publication_passage_service import PublicationPassageService
from ...services.publication_service import PublicationService
from ...services.review_context_service import ReviewContextService
from ...services.review_preparation_queue import ReviewPreparationQueue

logger = logging.getLogger(__name__)


# Global instances - initialized once per application lifecycle
_api_client: PubTator3Client | None = None
_publication_service: PublicationService | None = None
_publication_passage_service: PublicationPassageService | None = None
_logger: FilteringBoundLogger | None = None
_review_pool: asyncpg.Pool | None = None
_review_repository: PostgresReviewReragRepository | None = None
_review_queue: ReviewPreparationQueue | None = None
_review_context_service: ReviewContextService | None = None


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


async def get_publication_passage_service() -> PublicationPassageService:
    """Get compact publication passage service instance."""
    global _publication_passage_service
    if _publication_passage_service is None:
        _publication_passage_service = PublicationPassageService(
            publication_service=await get_publication_service()
        )
    return _publication_passage_service


async def get_review_pool() -> asyncpg.Pool:
    """Get asyncpg pool for review re-RAG storage."""
    global _review_pool
    if review_rerag_config.database_url is None:
        raise RuntimeError("PUBTATOR_LINK_DATABASE_URL is required for review re-RAG")
    if _review_pool is None:
        _review_pool = await asyncpg.create_pool(
            dsn=review_rerag_config.database_url,
            min_size=1,
            max_size=max(2, review_rerag_config.prep_concurrency * 2 + 2),
        )
    return _review_pool


async def get_review_repository() -> PostgresReviewReragRepository:
    """Get review re-RAG repository."""
    global _review_repository
    if _review_repository is None:
        _review_repository = PostgresReviewReragRepository(await get_review_pool())
    return _review_repository


async def get_review_queue() -> ReviewPreparationQueue:
    """Get review preparation queue."""
    global _review_queue
    if _review_queue is None:
        repository = await get_review_repository()
        client = await get_api_client()
        logger_instance = await get_logger()
        preparation = FullTextPreparationService(
            config=review_rerag_config,
            repository=repository,
            pubtator_client=client,
            logger=logger_instance,
        )
        _review_queue = ReviewPreparationQueue(
            config=review_rerag_config,
            repository=repository,
            preparation=preparation,
            logger=logger_instance,
        )
    return _review_queue


async def get_review_context_service() -> ReviewContextService:
    """Get review context retrieval service."""
    global _review_context_service
    if _review_context_service is None:
        _review_context_service = ReviewContextService(repository=await get_review_repository())
    return _review_context_service


# Type aliases for dependency injection
LoggerDep = Annotated[FilteringBoundLogger, Depends(get_logger)]
ClientDep = Annotated[PubTator3Client, Depends(get_api_client)]
PublicationServiceDep = Annotated[PublicationService, Depends(get_publication_service)]
PublicationPassageServiceDep = Annotated[
    PublicationPassageService, Depends(get_publication_passage_service)
]
ReviewQueueDep = Annotated[ReviewPreparationQueue, Depends(get_review_queue)]
ReviewContextServiceDep = Annotated[ReviewContextService, Depends(get_review_context_service)]


def handle_api_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    """Handle common API errors and convert to HTTP exceptions."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            # Re-raise HTTP exceptions as-is (from route-level error handling)
            raise
        except ValueError as e:
            # Client-side validation errors
            raise HTTPException(status_code=400, detail=str(e)) from e
        except ConnectionError as e:
            # Network/connection errors
            raise HTTPException(status_code=503, detail="Service temporarily unavailable") from e
        except TimeoutError as e:
            # Request timeout errors
            raise HTTPException(status_code=504, detail="Request timeout") from e
        except Exception as e:
            # Generic server errors
            logger.error(f"Unexpected error in {func.__name__}: {e}")
            raise HTTPException(status_code=500, detail="Internal server error") from e

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


async def cleanup_dependencies() -> None:
    """Cleanup function for graceful shutdown."""
    global _api_client, _publication_passage_service, _publication_service, _logger
    global _review_context_service, _review_pool, _review_queue, _review_repository

    if _api_client:
        api_client = _api_client
        _api_client = None
        try:
            await api_client.close()
        except RuntimeError as exc:
            if str(exc) != "Event loop is closed":
                raise

    if _review_queue:
        await _review_queue.stop()
        _review_queue = None

    if _review_pool:
        await _review_pool.close()
        _review_pool = None

    _review_repository = None
    _review_context_service = None
    _publication_passage_service = None
    _publication_service = None
    _logger = None
