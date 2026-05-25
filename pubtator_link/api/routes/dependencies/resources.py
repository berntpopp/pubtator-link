"""Application-scoped dependency resources."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

import asyncpg
from fastapi import Request
from structlog.typing import FilteringBoundLogger

from pubtator_link.api.client import PubTator3Client
from pubtator_link.config import review_rerag_config, settings
from pubtator_link.db.migrate import (
    ReviewSchemaDiagnostics,
    apply_migrations,
    inspect_review_schema,
)
from pubtator_link.repositories.review_rerag import PostgresReviewReragRepository
from pubtator_link.services.citation_graph import CitationGraphService
from pubtator_link.services.clinvar import ClinVarService
from pubtator_link.services.corpus_suggestion import CorpusSuggestionService
from pubtator_link.services.diagnostics import DiagnosticsService
from pubtator_link.services.errors import ReviewSchemaStaleError
from pubtator_link.services.europe_pmc import EuropePmcClient
from pubtator_link.services.literature_providers import (
    CrossrefClient,
    EuropePmcLiteratureClient,
    OpenAlexClient,
    UnpaywallClient,
)
from pubtator_link.services.llm_review_context import LlmReviewContextService
from pubtator_link.services.ncbi_discovery import DiscoveryService, NcbiDiscoveryClient
from pubtator_link.services.publication_metadata import (
    NcbiPublicationMetadataClient,
    PublicationMetadataService,
)
from pubtator_link.services.publication_passage_service import PublicationPassageService
from pubtator_link.services.publication_service import PublicationService
from pubtator_link.services.related_evidence import RelatedEvidenceService
from pubtator_link.services.research_session import ResearchSessionService
from pubtator_link.services.review_audit import ReviewAuditService
from pubtator_link.services.review_context_service import ReviewContextService
from pubtator_link.services.review_evidence_certainty import ReviewEvidenceCertaintyService
from pubtator_link.services.review_index_lifecycle import ReviewIndexLifecycleService
from pubtator_link.services.review_preparation_queue import ReviewPreparationQueue
from pubtator_link.services.source_preflight import SourcePreflightService
from pubtator_link.services.topic_literature_map import TopicLiteratureMapService
from pubtator_link.services.variant_evidence import VariantEvidenceService


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
    crossref_client: CrossrefClient | None = None
    europe_pmc_literature_client: EuropePmcLiteratureClient | None = None
    openalex_client: OpenAlexClient | None = None
    unpaywall_client: UnpaywallClient | None = None
    citation_graph_service: CitationGraphService | None = None
    related_evidence_service: RelatedEvidenceService | None = None
    topic_literature_map_service: TopicLiteratureMapService | None = None
    europe_pmc_client: EuropePmcClient | None = None
    review_pool: asyncpg.Pool | None = None
    review_repository: PostgresReviewReragRepository | None = None
    review_queue: ReviewPreparationQueue | None = None
    review_context_service: ReviewContextService | None = None
    llm_review_context_service: LlmReviewContextService | None = None
    review_audit_service: ReviewAuditService | None = None
    review_evidence_certainty_service: ReviewEvidenceCertaintyService | None = None
    review_index_lifecycle_service: ReviewIndexLifecycleService | None = None
    source_preflight_service: SourcePreflightService | None = None
    research_session_service: ResearchSessionService | None = None
    schema_diagnostics: ReviewSchemaDiagnostics | None = None
    diagnostics_service: DiagnosticsService | None = None
    corpus_suggestion_service: CorpusSuggestionService | None = None
    clinvar_service: ClinVarService | None = None
    variant_evidence_service: VariantEvidenceService | None = None


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
    from pubtator_link.api.routes.dependencies.core_api import (
        _publication_metadata_coverage_provider,
    )
    from pubtator_link.api.routes.dependencies.discovery import (
        _TopicLiteratureMapSearchClient,
    )
    from pubtator_link.api.routes.dependencies.review import (
        _build_europe_pmc_client,
        _build_full_text_preparation,
        _build_review_context_service,
        _build_source_preflight_service,
    )

    api_client: PubTator3Client | None = None
    ncbi_discovery_client: NcbiDiscoveryClient | None = None
    ncbi_publication_metadata_client: NcbiPublicationMetadataClient | None = None
    crossref_client: CrossrefClient | None = None
    europe_pmc_literature_client: EuropePmcLiteratureClient | None = None
    openalex_client: OpenAlexClient | None = None
    unpaywall_client: UnpaywallClient | None = None
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
        crossref_client = CrossrefClient(mailto=settings.crossref_mailto)
        europe_pmc_literature_client = EuropePmcLiteratureClient(
            base_url=settings.europe_pmc_base_url,
        )
        openalex_client = OpenAlexClient(mailto=settings.openalex_mailto)
        unpaywall_client = UnpaywallClient(email=settings.unpaywall_email)
        citation_graph_service = CitationGraphService(
            crossref=crossref_client,
            europe_pmc=europe_pmc_literature_client,
            openalex=openalex_client,
            unpaywall=unpaywall_client,
            discovery_service=discovery_service,
            metadata_service=publication_metadata_service,
        )
        related_evidence_service = RelatedEvidenceService(
            discovery_service=discovery_service,
            metadata_service=publication_metadata_service,
            citation_graph_service=citation_graph_service,
        )
        topic_literature_map_service = TopicLiteratureMapService(
            search_client=_TopicLiteratureMapSearchClient(api_client),
            metadata_service=publication_metadata_service,
            citation_graph_service=citation_graph_service,
            related_evidence_service=related_evidence_service,
        )
        clinvar_service = ClinVarService()
        variant_evidence_service = VariantEvidenceService(
            clinvar=clinvar_service,
            pubtator_client=api_client,
            metadata_service=publication_metadata_service,
        )
        europe_pmc_client = _build_europe_pmc_client(api_client)
        source_preflight_service = _build_source_preflight_service(
            api_client=api_client,
            discovery_service=discovery_service,
            europe_pmc_client=europe_pmc_client,
        )

        review_repository: PostgresReviewReragRepository | None = None
        review_context_service: ReviewContextService | None = None
        llm_review_context_service: LlmReviewContextService | None = None

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
                raise ReviewSchemaStaleError(f"Review database schema is not current: {missing}")
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
            review_context_service = _build_review_context_service(
                review_repository,
                publication_metadata_service=publication_metadata_service,
            )
            llm_review_context_service = LlmReviewContextService(repository=review_repository)
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
            crossref_client=crossref_client,
            europe_pmc_literature_client=europe_pmc_literature_client,
            openalex_client=openalex_client,
            unpaywall_client=unpaywall_client,
            citation_graph_service=citation_graph_service,
            related_evidence_service=related_evidence_service,
            topic_literature_map_service=topic_literature_map_service,
            europe_pmc_client=europe_pmc_client,
            source_preflight_service=source_preflight_service,
            review_pool=review_pool,
            review_repository=review_repository,
            review_queue=review_queue,
            review_context_service=review_context_service,
            llm_review_context_service=llm_review_context_service,
            review_audit_service=review_audit_service,
            review_evidence_certainty_service=review_evidence_certainty_service,
            review_index_lifecycle_service=review_index_lifecycle_service,
            schema_diagnostics=schema_diagnostics,
            diagnostics_service=diagnostics_service,
            clinvar_service=clinvar_service,
            variant_evidence_service=variant_evidence_service,
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
        if europe_pmc_literature_client is not None:
            await europe_pmc_literature_client.close()
        if openalex_client is not None:
            await openalex_client.close()
        if unpaywall_client is not None:
            await unpaywall_client.close()
        if crossref_client is not None:
            await crossref_client.close()
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
    if resources.europe_pmc_literature_client is not None:
        await resources.europe_pmc_literature_client.close()
    if resources.openalex_client is not None:
        await resources.openalex_client.close()
    if resources.unpaywall_client is not None:
        await resources.unpaywall_client.close()
    if resources.crossref_client is not None:
        await resources.crossref_client.close()
    await resources.api_client.close()
