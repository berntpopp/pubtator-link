"""Shared dependencies and dependency injection for FastAPI routes."""

import functools
import logging
from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Annotated, Any

import asyncpg
import httpx
from fastapi import Depends, HTTPException, Request
from structlog.typing import FilteringBoundLogger

from pubtator_link.api.search_filters import merge_search_filters
from pubtator_link.db.migrate import (
    ReviewSchemaDiagnostics,
    apply_migrations,
    inspect_review_schema,
)
from pubtator_link.models.responses import SearchResponse, SearchResult
from pubtator_link.models.review_rerag import StageResearchSessionRequest

from ...api.client import PubTator3Client
from ...config import review_rerag_config
from ...logging_config import configure_logging
from ...models.review_rerag import CoverageReason, CoverageTier
from ...repositories.review_rerag import PostgresReviewReragRepository
from ...services.corpus_suggestion import CorpusSuggestionService
from ...services.diagnostics import DiagnosticsService
from ...services.europe_pmc import EuropePmcClient
from ...services.full_text_preparation import FullTextPreparationService
from ...services.ncbi_discovery import DiscoveryService, NcbiDiscoveryClient
from ...services.publication_metadata import (
    NcbiPublicationMetadataClient,
    PublicationMetadataService,
)
from ...services.publication_passage_service import PublicationPassageService
from ...services.publication_service import PublicationService
from ...services.research_session import ResearchSessionSearchProvider, ResearchSessionService
from ...services.review_audit import ReviewAuditService
from ...services.review_context_service import ReviewContextService
from ...services.review_evidence_certainty import ReviewEvidenceCertaintyService
from ...services.review_index_lifecycle import ReviewIndexLifecycleService
from ...services.review_preparation_queue import ReviewPreparationQueue
from ...services.source_preflight import SourcePreflightService

logger = logging.getLogger(__name__)


# Global instances - initialized once per application lifecycle
_api_client: PubTator3Client | None = None
_publication_service: PublicationService | None = None
_publication_passage_service: PublicationPassageService | None = None
_publication_metadata_service: PublicationMetadataService | None = None
_ncbi_publication_metadata_client: NcbiPublicationMetadataClient | None = None
_ncbi_discovery_client: NcbiDiscoveryClient | None = None
_discovery_service: DiscoveryService | None = None
_logger: FilteringBoundLogger | None = None
_review_pool: asyncpg.Pool | None = None
_review_repository: PostgresReviewReragRepository | None = None
_review_queue: ReviewPreparationQueue | None = None
_review_context_service: ReviewContextService | None = None
_review_audit_service: ReviewAuditService | None = None
_review_evidence_certainty_service: ReviewEvidenceCertaintyService | None = None
_review_index_lifecycle_service: ReviewIndexLifecycleService | None = None
_source_preflight_service: SourcePreflightService | None = None
_research_session_service: ResearchSessionService | None = None
_diagnostics_service: DiagnosticsService | None = None
_corpus_suggestion_service: CorpusSuggestionService | None = None


@dataclass
class AppResources:
    """Runtime resources owned by one FastAPI application lifespan."""

    logger: FilteringBoundLogger
    api_client: PubTator3Client
    publication_service: PublicationService
    publication_passage_service: PublicationPassageService
    ncbi_publication_metadata_client: NcbiPublicationMetadataClient | None = None
    publication_metadata_service: PublicationMetadataService | None = None
    ncbi_discovery_client: NcbiDiscoveryClient | None = None
    discovery_service: DiscoveryService | None = None
    europe_pmc_client: EuropePmcClient | None = None
    review_pool: asyncpg.Pool | None = None
    review_repository: PostgresReviewReragRepository | None = None
    review_queue: ReviewPreparationQueue | None = None
    review_context_service: ReviewContextService | None = None
    review_audit_service: ReviewAuditService | None = None
    review_evidence_certainty_service: ReviewEvidenceCertaintyService | None = None
    review_index_lifecycle_service: ReviewIndexLifecycleService | None = None
    source_preflight_service: SourcePreflightService | None = None
    research_session_service: ResearchSessionService | None = None
    schema_diagnostics: ReviewSchemaDiagnostics | None = None
    diagnostics_service: DiagnosticsService | None = None
    corpus_suggestion_service: CorpusSuggestionService | None = None


_app_resources_context: ContextVar[AppResources | None] = ContextVar(
    "pubtator_app_resources",
    default=None,
)


def bind_app_resources(resources: AppResources) -> Token[AppResources | None]:
    """Bind app resources to the current request context."""
    return _app_resources_context.set(resources)


def reset_app_resources(token: Token[AppResources | None]) -> None:
    """Reset the current request context resource binding."""
    _app_resources_context.reset(token)


def current_app_resources() -> AppResources | None:
    """Return resources bound to the current request context, if any."""
    return _app_resources_context.get()


def resources_from_request(request: Request) -> AppResources:
    """Return app-scoped resources for route dependency resolution."""
    resources = getattr(request.app.state, "pubtator_resources", None)
    if not isinstance(resources, AppResources):
        raise RuntimeError("Application resources are not initialized")
    return resources


def review_pool_kwargs() -> dict[str, Any]:
    """Return asyncpg pool arguments for review re-RAG storage."""
    if review_rerag_config.database_url is None:
        raise RuntimeError("PUBTATOR_LINK_DATABASE_URL is required for review re-RAG")
    # Pool sizing: cover the worst concurrent demand (prep workers + retrieval
    # queries + occasional audit writes) with headroom. Floor of 10 prevents
    # the default 2-prep-worker config from saturating under 4 concurrent batch
    # retrievals each issuing 4 inner queries.
    prep = review_rerag_config.prep_concurrency
    retrieval = getattr(review_rerag_config, "retrieval_concurrency", 4)
    return {
        "dsn": review_rerag_config.database_url,
        "min_size": min(4, max(1, prep)),
        "max_size": max(10, prep * 2 + retrieval * 2 + 4),
    }


async def create_app_resources(logger: FilteringBoundLogger) -> AppResources:
    """Create resources owned by one FastAPI application lifespan."""
    api_client: PubTator3Client | None = None
    ncbi_discovery_client: NcbiDiscoveryClient | None = None
    ncbi_publication_metadata_client: NcbiPublicationMetadataClient | None = None
    review_pool: asyncpg.Pool | None = None
    review_queue: ReviewPreparationQueue | None = None
    review_audit_service: ReviewAuditService | None = None
    review_evidence_certainty_service: ReviewEvidenceCertaintyService | None = None
    review_index_lifecycle_service: ReviewIndexLifecycleService | None = None
    schema_diagnostics: ReviewSchemaDiagnostics | None = None

    try:
        api_client = PubTator3Client(logger=logger)
        publication_service = PublicationService(client=api_client, logger=logger)
        publication_passage_service = PublicationPassageService(
            publication_service=publication_service
        )
        ncbi_publication_metadata_client = NcbiPublicationMetadataClient()
        publication_metadata_service = PublicationMetadataService(
            client=ncbi_publication_metadata_client,
            coverage_provider=_publication_metadata_coverage_provider,
        )
        ncbi_discovery_client = NcbiDiscoveryClient()
        discovery_service = DiscoveryService(ncbi_discovery_client)
        europe_pmc_client = _build_europe_pmc_client(api_client)
        source_preflight_service = _build_source_preflight_service(
            api_client=api_client,
            discovery_service=discovery_service,
            europe_pmc_client=europe_pmc_client,
        )

        review_repository: PostgresReviewReragRepository | None = None
        review_context_service: ReviewContextService | None = None

        if review_rerag_config.database_url is not None:
            if getattr(review_rerag_config, "auto_migrate", False):
                await apply_migrations(review_rerag_config.database_url)
            schema_diagnostics = await inspect_review_schema(review_rerag_config.database_url)
            if (
                getattr(review_rerag_config, "require_schema_current", False)
                and not schema_diagnostics.current
            ):
                missing = ", ".join(
                    [*schema_diagnostics.missing_tables, *schema_diagnostics.missing_columns]
                )
                raise RuntimeError(f"Review database schema is not current: {missing}")
            review_pool = await asyncpg.create_pool(**review_pool_kwargs())
            review_repository = PostgresReviewReragRepository(review_pool)
            preparation = _build_full_text_preparation(
                repository=review_repository,
                client=api_client,
                logger_instance=logger,
                europe_pmc_client=europe_pmc_client,
            )
            review_queue = ReviewPreparationQueue(
                config=review_rerag_config,
                repository=review_repository,
                preparation=preparation,
                logger=logger,
            )
            review_context_service = _build_review_context_service(review_repository)
            review_audit_service = ReviewAuditService(repository=review_repository)
            review_evidence_certainty_service = ReviewEvidenceCertaintyService(
                repository=review_repository
            )
            review_index_lifecycle_service = ReviewIndexLifecycleService(
                repository=review_repository,
                config=review_rerag_config,
            )

        async def inspect_schema_for_diagnostics() -> ReviewSchemaDiagnostics:
            return await inspect_review_schema(review_rerag_config.database_url)

        diagnostics_service = DiagnosticsService(
            inspect_schema=inspect_schema_for_diagnostics,
            review_queue_available=lambda: review_queue is not None,
            europe_pmc_enabled=lambda: europe_pmc_client is not None,
        )

        return AppResources(
            logger=logger,
            api_client=api_client,
            publication_service=publication_service,
            publication_passage_service=publication_passage_service,
            ncbi_publication_metadata_client=ncbi_publication_metadata_client,
            publication_metadata_service=publication_metadata_service,
            ncbi_discovery_client=ncbi_discovery_client,
            discovery_service=discovery_service,
            europe_pmc_client=europe_pmc_client,
            source_preflight_service=source_preflight_service,
            review_pool=review_pool,
            review_repository=review_repository,
            review_queue=review_queue,
            review_context_service=review_context_service,
            review_audit_service=review_audit_service,
            review_evidence_certainty_service=review_evidence_certainty_service,
            review_index_lifecycle_service=review_index_lifecycle_service,
            schema_diagnostics=schema_diagnostics,
            diagnostics_service=diagnostics_service,
        )
    except Exception:
        if review_queue is not None:
            await review_queue.stop()
        if review_pool is not None:
            await review_pool.close()
        if ncbi_discovery_client is not None:
            await ncbi_discovery_client.close()
        if ncbi_publication_metadata_client is not None:
            await ncbi_publication_metadata_client.close()
        if api_client is not None:
            await api_client.close()
        raise


async def close_app_resources(resources: AppResources) -> None:
    """Close resources owned by one FastAPI application lifespan."""
    if resources.review_queue is not None:
        await resources.review_queue.stop()
    if resources.review_pool is not None:
        await resources.review_pool.close()
    if resources.ncbi_discovery_client is not None:
        await resources.ncbi_discovery_client.close()
    if resources.ncbi_publication_metadata_client is not None:
        await resources.ncbi_publication_metadata_client.close()
    await resources.api_client.close()


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
    preflight = await get_source_preflight_service()
    hints = await preflight.preflight_pmids(pmids)
    return {hint.pmid: (hint.expected_coverage, hint.coverage_reason) for hint in hints}


async def get_discovery_service() -> DiscoveryService:
    """Get NCBI discovery service."""
    global _ncbi_discovery_client, _discovery_service
    resources = current_app_resources()
    if resources is not None:
        if resources.discovery_service is None:
            if resources.ncbi_discovery_client is None:
                resources.ncbi_discovery_client = NcbiDiscoveryClient()
            resources.discovery_service = DiscoveryService(resources.ncbi_discovery_client)
        return resources.discovery_service
    if _discovery_service is None:
        if _ncbi_discovery_client is None:
            _ncbi_discovery_client = NcbiDiscoveryClient()
        _discovery_service = DiscoveryService(_ncbi_discovery_client)
    return _discovery_service


async def get_diagnostics_service() -> DiagnosticsService:
    """Get subsystem diagnostics service."""
    global _diagnostics_service
    resources = current_app_resources()
    if resources is not None:
        if resources.diagnostics_service is None:
            resources.diagnostics_service = _build_diagnostics_service(resources)
        return resources.diagnostics_service
    if _diagnostics_service is None:
        _diagnostics_service = _build_diagnostics_service(None)
    return _diagnostics_service


async def get_corpus_suggestion_service() -> CorpusSuggestionService:
    """Get deterministic corpus suggestion service."""
    global _corpus_suggestion_service
    resources = current_app_resources()
    if resources is not None:
        if resources.corpus_suggestion_service is None:
            resources.corpus_suggestion_service = CorpusSuggestionService(
                search_client=_CorpusSuggestionSearchClient(resources.api_client),
                metadata_service=await get_publication_metadata_service(),
                source_preflight_service=await get_source_preflight_service(),
            )
        return resources.corpus_suggestion_service
    if _corpus_suggestion_service is None:
        _corpus_suggestion_service = CorpusSuggestionService(
            search_client=_CorpusSuggestionSearchClient(await get_api_client()),
            metadata_service=await get_publication_metadata_service(),
            source_preflight_service=await get_source_preflight_service(),
        )
    return _corpus_suggestion_service


class _CorpusSuggestionSearchClient:
    def __init__(self, client: PubTator3Client) -> None:
        self.client = client

    async def search(self, query: str, *, limit: int, sort: str | None) -> dict[str, Any]:
        raw = await self.client.search_publications(text=query, page=1, sort=sort)
        results = list(raw.get("results", []))
        return {**raw, "results": results[:limit]}


def _build_diagnostics_service(resources: AppResources | None) -> DiagnosticsService:
    async def inspect_schema_for_diagnostics() -> ReviewSchemaDiagnostics:
        return await inspect_review_schema(review_rerag_config.database_url)

    return DiagnosticsService(
        inspect_schema=inspect_schema_for_diagnostics,
        review_queue_available=lambda: (
            resources.review_queue is not None
            if resources is not None
            else _review_queue is not None
        ),
        europe_pmc_enabled=lambda: (
            resources.europe_pmc_client is not None
            if resources is not None
            else getattr(review_rerag_config, "enable_europe_pmc_fallback", False)
        ),
    )


async def get_review_pool() -> asyncpg.Pool:
    """Get fallback asyncpg pool for review re-RAG storage."""
    global _review_pool
    if _review_pool is None:
        _review_pool = await asyncpg.create_pool(**review_pool_kwargs())
    return _review_pool


async def get_review_repository() -> PostgresReviewReragRepository:
    """Get review re-RAG repository."""
    global _review_repository
    resources = current_app_resources()
    if resources is not None:
        if resources.review_repository is None:
            raise RuntimeError("PUBTATOR_LINK_DATABASE_URL is required for review re-RAG")
        return resources.review_repository
    if _review_repository is None:
        _review_repository = PostgresReviewReragRepository(await get_review_pool())
    return _review_repository


async def get_review_queue() -> ReviewPreparationQueue:
    """Get review preparation queue."""
    global _review_queue
    resources = current_app_resources()
    if resources is not None:
        if resources.review_queue is None:
            raise RuntimeError("PUBTATOR_LINK_DATABASE_URL is required for review re-RAG")
        return resources.review_queue
    if _review_queue is None:
        repository = await get_review_repository()
        client = await get_api_client()
        logger_instance = await get_logger()
        preparation = _build_full_text_preparation(
            repository=repository,
            client=client,
            logger_instance=logger_instance,
            europe_pmc_client=_build_europe_pmc_client(client),
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
    resources = current_app_resources()
    if resources is not None:
        if resources.review_context_service is None:
            raise RuntimeError("PUBTATOR_LINK_DATABASE_URL is required for review re-RAG")
        return resources.review_context_service
    if _review_context_service is None:
        _review_context_service = _build_review_context_service(await get_review_repository())
    return _review_context_service


def _build_review_context_service(
    repository: PostgresReviewReragRepository,
) -> ReviewContextService:
    try:
        return ReviewContextService(
            repository=repository,
            retrieval_concurrency=getattr(review_rerag_config, "retrieval_concurrency", 4),
        )
    except TypeError:
        return ReviewContextService(repository)


async def get_source_preflight_service() -> SourcePreflightService:
    """Get review source preflight service."""
    global _source_preflight_service
    resources = current_app_resources()
    if resources is not None:
        if resources.source_preflight_service is None:
            resources.source_preflight_service = _build_source_preflight_service(
                api_client=resources.api_client,
                discovery_service=await get_discovery_service(),
                europe_pmc_client=resources.europe_pmc_client,
            )
        return resources.source_preflight_service
    if _source_preflight_service is None:
        client = await get_api_client()
        _source_preflight_service = _build_source_preflight_service(
            api_client=client,
            discovery_service=await get_discovery_service(),
            europe_pmc_client=_build_europe_pmc_client(client),
        )
    return _source_preflight_service


def _build_source_preflight_service(
    *,
    api_client: PubTator3Client,
    discovery_service: DiscoveryService,
    europe_pmc_client: EuropePmcClient | None = None,
) -> SourcePreflightService:
    async def id_converter(pmid: str) -> dict[str, str | None]:
        converted = await discovery_service.convert_article_ids([pmid], source="auto")
        record = next(
            (
                record
                for record in converted.records
                if record.input_id == pmid or record.pmid == pmid
            ),
            None,
        )
        if record is None:
            return {"id_resolution_status": "unresolved"}
        return {
            "pmcid": record.pmcid,
            "doi": record.doi,
            "id_resolution_status": record.status,
            "id_resolution_reason": record.reason,
        }

    return SourcePreflightService.from_pubtator_client(
        api_client,
        id_converter=id_converter,
        preflight_concurrency=getattr(review_rerag_config, "preflight_concurrency", 3),
        europe_pmc_client=europe_pmc_client,
    )


def _build_europe_pmc_client(client: PubTator3Client) -> EuropePmcClient | None:
    if not getattr(review_rerag_config, "enable_europe_pmc_fallback", False):
        return None
    return EuropePmcClient(
        http_client=client.client,
        base_url=getattr(
            review_rerag_config,
            "europe_pmc_base_url",
            "https://www.ebi.ac.uk/europepmc/webservices/rest",
        ),
    )


def _build_full_text_preparation(
    *,
    repository: PostgresReviewReragRepository,
    client: PubTator3Client,
    logger_instance: FilteringBoundLogger,
    europe_pmc_client: EuropePmcClient | None,
) -> FullTextPreparationService:
    kwargs: dict[str, Any] = {
        "config": review_rerag_config,
        "repository": repository,
        "pubtator_client": client,
        "logger": logger_instance,
    }
    if europe_pmc_client is not None:
        kwargs["europe_pmc_client"] = europe_pmc_client
    return FullTextPreparationService(**kwargs)


async def get_review_audit_service() -> ReviewAuditService:
    """Get review audit export service."""
    global _review_audit_service
    resources = current_app_resources()
    if resources is not None:
        if resources.review_audit_service is None:
            if resources.review_repository is None:
                raise RuntimeError("PUBTATOR_LINK_DATABASE_URL is required for review re-RAG")
            resources.review_audit_service = ReviewAuditService(resources.review_repository)
        return resources.review_audit_service
    if _review_audit_service is None:
        _review_audit_service = ReviewAuditService(await get_review_repository())
    return _review_audit_service


async def get_review_index_lifecycle_service() -> ReviewIndexLifecycleService:
    """Get review index lifecycle service."""
    global _review_index_lifecycle_service
    resources = current_app_resources()
    if resources is not None:
        if resources.review_index_lifecycle_service is None:
            if resources.review_repository is None:
                raise RuntimeError("PUBTATOR_LINK_DATABASE_URL is required for review re-RAG")
            resources.review_index_lifecycle_service = ReviewIndexLifecycleService(
                repository=resources.review_repository,
                config=review_rerag_config,
            )
        return resources.review_index_lifecycle_service
    if _review_index_lifecycle_service is None:
        _review_index_lifecycle_service = ReviewIndexLifecycleService(
            repository=await get_review_repository(),
            config=review_rerag_config,
        )
    return _review_index_lifecycle_service


async def get_review_evidence_certainty_service() -> ReviewEvidenceCertaintyService:
    """Get review evidence certainty service."""
    global _review_evidence_certainty_service
    resources = current_app_resources()
    if resources is not None:
        if resources.review_evidence_certainty_service is None:
            if resources.review_repository is None:
                raise RuntimeError("PUBTATOR_LINK_DATABASE_URL is required for review re-RAG")
            resources.review_evidence_certainty_service = ReviewEvidenceCertaintyService(
                repository=resources.review_repository
            )
        return resources.review_evidence_certainty_service
    if _review_evidence_certainty_service is None:
        _review_evidence_certainty_service = ReviewEvidenceCertaintyService(
            repository=await get_review_repository()
        )
    return _review_evidence_certainty_service


async def get_research_session_service() -> ResearchSessionService:
    """Get transparent research session staging service."""
    global _research_session_service
    resources = current_app_resources()
    if resources is not None:
        if resources.research_session_service is None:
            if resources.review_repository is None or resources.review_queue is None:
                raise RuntimeError("PUBTATOR_LINK_DATABASE_URL is required for review re-RAG")
            resources.research_session_service = ResearchSessionService(
                repository=resources.review_repository,
                search_provider=_RouteSearchProvider(resources.api_client),
                preflight_service=resources.source_preflight_service,
                queue=resources.review_queue,
            )
        return resources.research_session_service
    if _research_session_service is None:
        _research_session_service = ResearchSessionService(
            repository=await get_review_repository(),
            search_provider=_RouteSearchProvider(await get_api_client()),
            preflight_service=await get_source_preflight_service(),
            queue=await get_review_queue(),
        )
    return _research_session_service


class _RouteSearchProvider(ResearchSessionSearchProvider):
    def __init__(self, client: PubTator3Client) -> None:
        self.client = client

    async def search(self, request: StageResearchSessionRequest) -> SearchResponse:
        raw = await self.client.search_publications(
            text=request.query or "",
            page=request.page,
            sort=request.sort,
            filters=merge_search_filters(
                filters=request.filters,
                publication_types=request.publication_types,
                year_min=request.year_min,
                year_max=request.year_max,
            ),
            sections=",".join(request.sections) if request.sections else None,
        )
        results = [
            SearchResult(
                pmid=item.get("pmid", ""),
                title=item.get("title", ""),
                abstract=item.get("abstract"),
                authors=item.get("authors", []),
                journal=item.get("journal"),
                pub_date=item.get("pub_date")
                or item.get("meta_date_publication")
                or item.get("date"),
                annotations=item.get("annotations", []),
                score=item.get("score"),
                pmcid=item.get("pmcid"),
                doi=item.get("doi"),
                date=item.get("date"),
                text_hl=item.get("text_hl"),
                citations=item.get("citations"),
                volume=item.get("volume") or item.get("meta_volume"),
                issue=item.get("issue") or item.get("meta_issue"),
                pages=item.get("pages") or item.get("meta_pages"),
                publication_types=item.get("publication_types", []),
            )
            for item in raw.get("results", [])
        ]
        total_results = int(raw.get("count", raw.get("total", 0)))
        per_page = int(raw.get("page_size", raw.get("per_page", 20)))
        return SearchResponse(
            success=True,
            query=request.query or "",
            results=results,
            total_results=total_results,
            page=request.page,
            per_page=per_page,
            total_pages=int(
                raw.get(
                    "total_pages",
                    (total_results + per_page - 1) // per_page if per_page else 0,
                )
            ),
            sort_order=request.sort,
        )


# Type aliases for dependency injection
LoggerDep = Annotated[FilteringBoundLogger, Depends(get_logger)]
ClientDep = Annotated[PubTator3Client, Depends(get_api_client)]
PublicationServiceDep = Annotated[PublicationService, Depends(get_publication_service)]
PublicationPassageServiceDep = Annotated[
    PublicationPassageService, Depends(get_publication_passage_service)
]
PublicationMetadataServiceDep = Annotated[
    PublicationMetadataService, Depends(get_publication_metadata_service)
]
CorpusSuggestionServiceDep = Annotated[
    CorpusSuggestionService, Depends(get_corpus_suggestion_service)
]
DiscoveryServiceDep = Annotated[DiscoveryService, Depends(get_discovery_service)]
ReviewQueueDep = Annotated[ReviewPreparationQueue, Depends(get_review_queue)]
ReviewContextServiceDep = Annotated[ReviewContextService, Depends(get_review_context_service)]
ReviewAuditServiceDep = Annotated[ReviewAuditService, Depends(get_review_audit_service)]
ReviewEvidenceCertaintyServiceDep = Annotated[
    ReviewEvidenceCertaintyService,
    Depends(get_review_evidence_certainty_service),
]
ReviewIndexLifecycleServiceDep = Annotated[
    ReviewIndexLifecycleService,
    Depends(get_review_index_lifecycle_service),
]
SourcePreflightServiceDep = Annotated[SourcePreflightService, Depends(get_source_preflight_service)]
ResearchSessionServiceDep = Annotated[
    ResearchSessionService,
    Depends(get_research_session_service),
]


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
        except httpx.HTTPStatusError as e:
            # Upstream service returned an HTTP error response
            raise HTTPException(status_code=502, detail="Upstream service error") from e
        except httpx.RequestError as e:
            # Upstream service transport failures
            raise HTTPException(status_code=503, detail="Service temporarily unavailable") from e
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
    global _discovery_service, _ncbi_discovery_client, _ncbi_publication_metadata_client
    global _publication_metadata_service
    global _review_context_service, _review_pool, _review_queue, _review_repository
    global _review_evidence_certainty_service
    global _review_index_lifecycle_service
    global _research_session_service
    global _corpus_suggestion_service

    if _api_client:
        api_client = _api_client
        _api_client = None
        await api_client.close()

    if _ncbi_discovery_client:
        ncbi_discovery_client = _ncbi_discovery_client
        _ncbi_discovery_client = None
        await ncbi_discovery_client.close()

    if _ncbi_publication_metadata_client:
        publication_metadata_client = _ncbi_publication_metadata_client
        _ncbi_publication_metadata_client = None
        await publication_metadata_client.close()

    if _review_queue:
        await _review_queue.stop()
        _review_queue = None

    if _review_pool:
        await _review_pool.close()
        _review_pool = None

    _review_repository = None
    _review_context_service = None
    _review_evidence_certainty_service = None
    _review_index_lifecycle_service = None
    _research_session_service = None
    _corpus_suggestion_service = None
    _discovery_service = None
    _publication_passage_service = None
    _publication_metadata_service = None
    _publication_service = None
    _logger = None
