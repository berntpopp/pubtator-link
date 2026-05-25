"""Core PubTator API dependency providers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from structlog.typing import FilteringBoundLogger

from pubtator_link.api.client import PubTator3Client
from pubtator_link.api.routes.dependencies.resources import current_app_resources
from pubtator_link.logging_config import configure_logging
from pubtator_link.models.review_rerag import CoverageReason, CoverageTier
from pubtator_link.services.publication_metadata import (
    NcbiPublicationMetadataClient,
    PublicationMetadataService,
)
from pubtator_link.services.publication_passage_service import PublicationPassageService
from pubtator_link.services.publication_service import PublicationService

_api_client: PubTator3Client | None = None
_publication_service: PublicationService | None = None
_publication_passage_service: PublicationPassageService | None = None
_publication_metadata_service: PublicationMetadataService | None = None
_ncbi_publication_metadata_client: NcbiPublicationMetadataClient | None = None
_logger: FilteringBoundLogger | None = None


async def get_logger() -> FilteringBoundLogger:
    """Get structured logger instance."""
    global _logger
    resources = current_app_resources()
    if resources is not None:
        return resources.logger
    if _logger is None:
        _logger = configure_logging()
    return _logger


async def get_api_client() -> PubTator3Client:
    """Get PubTator3 API client instance."""
    global _api_client
    resources = current_app_resources()
    if resources is not None:
        return resources.api_client
    if _api_client is None:
        logger_instance = await get_logger()
        _api_client = PubTator3Client(logger=logger_instance)
    return _api_client


async def get_publication_service() -> PublicationService:
    """Get publication service instance."""
    global _publication_service
    resources = current_app_resources()
    if resources is not None:
        return resources.publication_service
    if _publication_service is None:
        client = await get_api_client()
        logger_instance = await get_logger()
        _publication_service = PublicationService(client=client, logger=logger_instance)
    return _publication_service


async def get_publication_passage_service() -> PublicationPassageService:
    """Get compact publication passage service."""
    global _publication_passage_service
    resources = current_app_resources()
    if resources is not None:
        return resources.publication_passage_service
    if _publication_passage_service is None:
        _publication_passage_service = PublicationPassageService(
            publication_service=await get_publication_service()
        )
    return _publication_passage_service


async def get_publication_metadata_service() -> PublicationMetadataService:
    """Get citation-grade publication metadata service."""
    global _ncbi_publication_metadata_client, _publication_metadata_service
    resources = current_app_resources()
    if resources is not None:
        if resources.publication_metadata_service is None:
            if resources.ncbi_publication_metadata_client is None:
                resources.ncbi_publication_metadata_client = NcbiPublicationMetadataClient()
            resources.publication_metadata_service = PublicationMetadataService(
                client=resources.ncbi_publication_metadata_client,
                coverage_provider=_publication_metadata_coverage_provider,
            )
        return resources.publication_metadata_service
    if _publication_metadata_service is None:
        if _ncbi_publication_metadata_client is None:
            _ncbi_publication_metadata_client = NcbiPublicationMetadataClient()
        _publication_metadata_service = PublicationMetadataService(
            client=_ncbi_publication_metadata_client,
            coverage_provider=_publication_metadata_coverage_provider,
        )
    return _publication_metadata_service


async def _publication_metadata_coverage_provider(
    pmids: list[str],
) -> dict[str, tuple[CoverageTier, CoverageReason]]:
    from pubtator_link.api.routes.dependencies.review import get_source_preflight_service

    preflight = await get_source_preflight_service()
    hints = await preflight.preflight_pmids(pmids)
    return {hint.pmid: (hint.expected_coverage, hint.coverage_reason) for hint in hints}


LoggerDep = Annotated[FilteringBoundLogger, Depends(get_logger)]
ClientDep = Annotated[PubTator3Client, Depends(get_api_client)]
PublicationServiceDep = Annotated[PublicationService, Depends(get_publication_service)]
PublicationPassageServiceDep = Annotated[
    PublicationPassageService, Depends(get_publication_passage_service)
]
PublicationMetadataServiceDep = Annotated[
    PublicationMetadataService, Depends(get_publication_metadata_service)
]


async def _cleanup_core_api_dependencies() -> None:
    global _api_client, _publication_passage_service, _publication_service, _logger
    global _ncbi_publication_metadata_client, _publication_metadata_service

    if _api_client:
        api_client = _api_client
        _api_client = None
        await api_client.close()

    if _ncbi_publication_metadata_client:
        publication_metadata_client = _ncbi_publication_metadata_client
        _ncbi_publication_metadata_client = None
        await publication_metadata_client.close()

    _publication_passage_service = None
    _publication_metadata_service = None
    _publication_service = None
    _logger = None
