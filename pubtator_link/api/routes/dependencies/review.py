"""Review re-RAG dependency providers."""

from __future__ import annotations

import logging
from typing import Annotated, Any

import asyncpg
from fastapi import Depends
from structlog.typing import FilteringBoundLogger

from pubtator_link.api.client import PubTator3Client
from pubtator_link.api.routes.dependencies.core_api import (
    get_api_client,
    get_logger,
    get_publication_metadata_service,
)
from pubtator_link.api.routes.dependencies.discovery import get_discovery_service
from pubtator_link.api.routes.dependencies.resources import (
    current_app_resources,
    review_pool_kwargs,
)
from pubtator_link.api.search_filters import apply_year_window, build_search_filter_plan
from pubtator_link.config import review_rerag_config
from pubtator_link.models.responses import SearchResponse, SearchResult
from pubtator_link.models.review_rerag import StageResearchSessionRequest
from pubtator_link.repositories.review_rerag import PostgresReviewReragRepository
from pubtator_link.services.europe_pmc import EuropePmcClient
from pubtator_link.services.full_text_preparation import FullTextPreparationService
from pubtator_link.services.llm_review_context import LlmReviewContextService
from pubtator_link.services.ncbi_discovery import DiscoveryService
from pubtator_link.services.publication_metadata import PublicationMetadataService
from pubtator_link.services.research_session import (
    ResearchSessionSearchProvider,
    ResearchSessionService,
)
from pubtator_link.services.review_audit import ReviewAuditService
from pubtator_link.services.review_context.embeddings import (
    EmbeddingProvider,
    EmbeddingProviderUnavailableError,
    SentenceTransformerEmbeddingProvider,
)
from pubtator_link.services.review_context_service import ReviewContextService
from pubtator_link.services.review_evidence_certainty import ReviewEvidenceCertaintyService
from pubtator_link.services.review_index_lifecycle import ReviewIndexLifecycleService
from pubtator_link.services.review_preparation_queue import ReviewPreparationQueue
from pubtator_link.services.source_preflight import SourcePreflightService

logger = logging.getLogger("pubtator_link.api.routes.dependencies")

_review_pool: asyncpg.Pool | None = None
_review_repository: PostgresReviewReragRepository | None = None
_review_queue: ReviewPreparationQueue | None = None
_review_context_service: ReviewContextService | None = None
_llm_review_context_service: LlmReviewContextService | None = None
_review_audit_service: ReviewAuditService | None = None
_review_evidence_certainty_service: ReviewEvidenceCertaintyService | None = None
_review_index_lifecycle_service: ReviewIndexLifecycleService | None = None
_source_preflight_service: SourcePreflightService | None = None
_research_session_service: ResearchSessionService | None = None


def _review_queue_available() -> bool:
    return _review_queue is not None


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
        _review_context_service = _build_review_context_service(
            await get_review_repository(),
            publication_metadata_service=await get_publication_metadata_service(),
        )
    return _review_context_service


def _build_review_context_service(
    repository: PostgresReviewReragRepository,
    publication_metadata_service: PublicationMetadataService | None = None,
) -> ReviewContextService:
    embedding_provider = _build_embedding_provider()
    try:
        return ReviewContextService(
            repository=repository,
            metadata_service=publication_metadata_service,
            retrieval_concurrency=getattr(review_rerag_config, "retrieval_concurrency", 4),
            embedding_provider=embedding_provider,
            embedding_rerank_enabled=getattr(
                review_rerag_config, "embedding_rerank_enabled", False
            ),
            embedding_model=getattr(
                review_rerag_config, "embedding_model", "BAAI/bge-small-en-v1.5"
            ),
            embedding_dim=getattr(review_rerag_config, "embedding_dim", 384),
            embedding_top_k=getattr(review_rerag_config, "embedding_top_k", 50),
            embedding_rrf_k=getattr(review_rerag_config, "embedding_rrf_k", 60),
        )
    except TypeError:
        return ReviewContextService(repository)


def _build_embedding_provider() -> EmbeddingProvider | None:
    if not getattr(review_rerag_config, "embedding_rerank_enabled", False):
        return None
    try:
        return SentenceTransformerEmbeddingProvider(
            model_name=getattr(review_rerag_config, "embedding_model", "BAAI/bge-small-en-v1.5"),
            dim=getattr(review_rerag_config, "embedding_dim", 384),
            device=getattr(review_rerag_config, "embedding_device", "auto"),
        )
    except EmbeddingProviderUnavailableError as exc:
        logger.warning(
            "Review embedding provider unavailable; lexical fallback active",
            extra={"error_type": type(exc).__name__},
        )
        return None


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
    embedding_provider = _build_embedding_provider()
    kwargs: dict[str, Any] = {
        "config": review_rerag_config,
        "repository": repository,
        "pubtator_client": client,
        "logger": logger_instance,
        "embedding_provider": embedding_provider,
        "embedding_model": getattr(
            review_rerag_config, "embedding_model", "BAAI/bge-small-en-v1.5"
        ),
        "embedding_dim": getattr(review_rerag_config, "embedding_dim", 384),
    }
    if europe_pmc_client is not None:
        kwargs["europe_pmc_client"] = europe_pmc_client
    try:
        return FullTextPreparationService(**kwargs)
    except TypeError:
        legacy_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key
            not in {
                "embedding_provider",
                "embedding_model",
                "embedding_dim",
                "europe_pmc_client",
            }
        }
        return FullTextPreparationService(**legacy_kwargs)


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


async def get_llm_review_context_service() -> LlmReviewContextService:
    """Get durable LLM review context service."""
    global _llm_review_context_service
    resources = current_app_resources()
    if resources is not None:
        if resources.llm_review_context_service is None:
            if resources.review_repository is None:
                raise RuntimeError("PUBTATOR_LINK_DATABASE_URL is required for review re-RAG")
            resources.llm_review_context_service = LlmReviewContextService(
                repository=resources.review_repository
            )
        return resources.llm_review_context_service
    if _llm_review_context_service is None:
        _llm_review_context_service = LlmReviewContextService(
            repository=await get_review_repository()
        )
    return _llm_review_context_service


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
        filter_plan = build_search_filter_plan(
            filters=request.filters,
            publication_types=request.publication_types,
            year_min=request.year_min,
            year_max=request.year_max,
            ignore_malformed_filters=False,
        )
        raw = await self.client.search_publications(
            text=request.query or "",
            page=request.page,
            sort=request.sort,
            filters=filter_plan.server_filters,
            sections=",".join(request.sections) if request.sections else None,
        )
        raw_results = list(raw.get("results", []))
        if filter_plan.has_local_year_window:
            # PubTator3 only filters by an exact year server-side; apply the
            # requested year range locally over this page (best-effort).
            raw_results = apply_year_window(
                raw_results, filter_plan.local_year_min, filter_plan.local_year_max
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
            for item in raw_results
        ]
        total_results = (
            len(raw_results)
            if filter_plan.has_local_year_window
            else int(raw.get("count", raw.get("total", 0)))
        )
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


ReviewQueueDep = Annotated[ReviewPreparationQueue, Depends(get_review_queue)]
ReviewContextServiceDep = Annotated[ReviewContextService, Depends(get_review_context_service)]
LlmReviewContextServiceDep = Annotated[
    LlmReviewContextService,
    Depends(get_llm_review_context_service),
]
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


async def _cleanup_review_dependencies() -> None:
    global _llm_review_context_service, _review_context_service, _review_pool
    global _review_queue, _review_repository
    global _review_evidence_certainty_service
    global _review_index_lifecycle_service
    global _research_session_service

    if _review_queue:
        await _review_queue.stop()
        _review_queue = None

    if _review_pool:
        await _review_pool.close()
        _review_pool = None

    _review_repository = None
    _review_context_service = None
    _llm_review_context_service = None
    _review_evidence_certainty_service = None
    _review_index_lifecycle_service = None
    _research_session_service = None
