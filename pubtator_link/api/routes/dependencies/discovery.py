"""Discovery and external literature dependency providers."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends

from pubtator_link.api.client import PubTator3Client
from pubtator_link.api.routes.dependencies.core_api import (
    get_api_client,
    get_publication_metadata_service,
)
from pubtator_link.api.routes.dependencies.resources import AppResources, current_app_resources
from pubtator_link.config import review_rerag_config, settings
from pubtator_link.db.migrate import ReviewSchemaDiagnostics, inspect_review_schema
from pubtator_link.services.citation_graph import CitationGraphService
from pubtator_link.services.clinvar import ClinVarService
from pubtator_link.services.corpus_suggestion import CorpusSuggestionService
from pubtator_link.services.diagnostics import DiagnosticsService
from pubtator_link.services.literature_providers import (
    CrossrefClient,
    EuropePmcLiteratureClient,
    OpenAlexClient,
    UnpaywallClient,
)
from pubtator_link.services.ncbi_discovery import DiscoveryService, NcbiDiscoveryClient
from pubtator_link.services.related_evidence import RelatedEvidenceService
from pubtator_link.services.topic_literature_map import TopicLiteratureMapService
from pubtator_link.services.variant_evidence import VariantEvidenceService

_ncbi_discovery_client: NcbiDiscoveryClient | None = None
_discovery_service: DiscoveryService | None = None
_crossref_client: CrossrefClient | None = None
_europe_pmc_literature_client: EuropePmcLiteratureClient | None = None
_openalex_client: OpenAlexClient | None = None
_unpaywall_client: UnpaywallClient | None = None
_citation_graph_service: CitationGraphService | None = None
_related_evidence_service: RelatedEvidenceService | None = None
_topic_literature_map_service: TopicLiteratureMapService | None = None
_diagnostics_service: DiagnosticsService | None = None
_corpus_suggestion_service: CorpusSuggestionService | None = None
_clinvar_service: ClinVarService | None = None
_variant_evidence_service: VariantEvidenceService | None = None


def _fallback_review_queue_available() -> bool:
    from pubtator_link.api.routes.dependencies.review import _review_queue_available

    return _review_queue_available()


async def get_discovery_service() -> DiscoveryService:
    """Get NCBI discovery service."""
    global _ncbi_discovery_client, _discovery_service
    resources = current_app_resources()
    if resources is not None:
        if resources.discovery_service is None:
            if resources.ncbi_discovery_client is None:
                resources.ncbi_discovery_client = NcbiDiscoveryClient()
            resources.discovery_service = DiscoveryService(
                resources.ncbi_discovery_client,
                metadata_service=await get_publication_metadata_service(),
            )
        return resources.discovery_service
    if _discovery_service is None:
        if _ncbi_discovery_client is None:
            _ncbi_discovery_client = NcbiDiscoveryClient()
        _discovery_service = DiscoveryService(
            _ncbi_discovery_client,
            metadata_service=await get_publication_metadata_service(),
        )
    return _discovery_service


async def get_citation_graph_service() -> CitationGraphService:
    """Get publication citation graph service."""
    global _citation_graph_service, _crossref_client, _europe_pmc_literature_client
    global _openalex_client, _unpaywall_client
    resources = current_app_resources()
    if resources is not None:
        if resources.citation_graph_service is None:
            if resources.crossref_client is None:
                resources.crossref_client = CrossrefClient(mailto=settings.crossref_mailto)
            if resources.europe_pmc_literature_client is None:
                resources.europe_pmc_literature_client = EuropePmcLiteratureClient(
                    base_url=settings.europe_pmc_base_url,
                )
            if resources.openalex_client is None:
                resources.openalex_client = OpenAlexClient(mailto=settings.openalex_mailto)
            if resources.unpaywall_client is None:
                resources.unpaywall_client = UnpaywallClient(email=settings.unpaywall_email)
            resources.citation_graph_service = CitationGraphService(
                crossref=resources.crossref_client,
                europe_pmc=resources.europe_pmc_literature_client,
                openalex=resources.openalex_client,
                unpaywall=resources.unpaywall_client,
                discovery_service=await get_discovery_service(),
                metadata_service=await get_publication_metadata_service(),
            )
        return resources.citation_graph_service
    if _citation_graph_service is None:
        if _crossref_client is None:
            _crossref_client = CrossrefClient(mailto=settings.crossref_mailto)
        if _europe_pmc_literature_client is None:
            _europe_pmc_literature_client = EuropePmcLiteratureClient(
                base_url=settings.europe_pmc_base_url,
            )
        if _openalex_client is None:
            _openalex_client = OpenAlexClient(mailto=settings.openalex_mailto)
        if _unpaywall_client is None:
            _unpaywall_client = UnpaywallClient(email=settings.unpaywall_email)
        _citation_graph_service = CitationGraphService(
            crossref=_crossref_client,
            europe_pmc=_europe_pmc_literature_client,
            openalex=_openalex_client,
            unpaywall=_unpaywall_client,
            discovery_service=await get_discovery_service(),
            metadata_service=await get_publication_metadata_service(),
        )
    return _citation_graph_service


async def get_related_evidence_service() -> RelatedEvidenceService:
    """Get related evidence candidate service."""
    global _related_evidence_service
    resources = current_app_resources()
    if resources is not None:
        if resources.related_evidence_service is None:
            resources.related_evidence_service = RelatedEvidenceService(
                discovery_service=await get_discovery_service(),
                metadata_service=await get_publication_metadata_service(),
                citation_graph_service=await get_citation_graph_service(),
            )
        return resources.related_evidence_service
    if _related_evidence_service is None:
        _related_evidence_service = RelatedEvidenceService(
            discovery_service=await get_discovery_service(),
            metadata_service=await get_publication_metadata_service(),
            citation_graph_service=await get_citation_graph_service(),
        )
    return _related_evidence_service


async def get_topic_literature_map_service() -> TopicLiteratureMapService:
    """Get topic-level literature map service."""
    global _topic_literature_map_service
    resources = current_app_resources()
    if resources is not None:
        if resources.topic_literature_map_service is None:
            resources.topic_literature_map_service = TopicLiteratureMapService(
                search_client=_TopicLiteratureMapSearchClient(resources.api_client),
                metadata_service=await get_publication_metadata_service(),
                citation_graph_service=await get_citation_graph_service(),
                related_evidence_service=await get_related_evidence_service(),
            )
        return resources.topic_literature_map_service
    if _topic_literature_map_service is None:
        _topic_literature_map_service = TopicLiteratureMapService(
            search_client=_TopicLiteratureMapSearchClient(await get_api_client()),
            metadata_service=await get_publication_metadata_service(),
            citation_graph_service=await get_citation_graph_service(),
            related_evidence_service=await get_related_evidence_service(),
        )
    return _topic_literature_map_service


async def get_clinvar_service() -> ClinVarService:
    """Get ClinVar lookup service."""
    global _clinvar_service
    resources = current_app_resources()
    if resources is not None:
        if resources.clinvar_service is None:
            resources.clinvar_service = ClinVarService()
        return resources.clinvar_service
    if _clinvar_service is None:
        _clinvar_service = ClinVarService()
    return _clinvar_service


async def get_variant_evidence_service() -> VariantEvidenceService:
    """Get variant evidence lookup service."""
    global _variant_evidence_service
    resources = current_app_resources()
    if resources is not None:
        if resources.variant_evidence_service is None:
            resources.variant_evidence_service = VariantEvidenceService(
                clinvar=await get_clinvar_service(),
                pubtator_client=resources.api_client,
                metadata_service=await get_publication_metadata_service(),
            )
        return resources.variant_evidence_service
    if _variant_evidence_service is None:
        _variant_evidence_service = VariantEvidenceService(
            clinvar=await get_clinvar_service(),
            pubtator_client=await get_api_client(),
            metadata_service=await get_publication_metadata_service(),
        )
    return _variant_evidence_service


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
    from pubtator_link.api.routes.dependencies.review import get_source_preflight_service

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


class _TopicLiteratureMapSearchClient:
    def __init__(self, client: PubTator3Client) -> None:
        self.client = client

    async def search_publications(
        self,
        text: str,
        *,
        page: int = 1,
        sort: str | None = None,
    ) -> dict[str, Any]:
        return await self.client.search_publications(text=text, page=page, sort=sort)


def _build_diagnostics_service(resources: AppResources | None) -> DiagnosticsService:
    async def inspect_schema_for_diagnostics() -> ReviewSchemaDiagnostics:
        return await inspect_review_schema(review_rerag_config.database_url)

    async def pubtator_api_status() -> dict[str, Any]:
        client = resources.api_client if resources is not None else await get_api_client()
        await client.search_publications(text="pubtator", page=1)
        return {"status": "ready", "probe": "search"}

    return DiagnosticsService(
        inspect_schema=inspect_schema_for_diagnostics,
        review_queue_available=lambda: (
            resources.review_queue is not None
            if resources is not None
            else _fallback_review_queue_available()
        ),
        europe_pmc_enabled=lambda: (
            resources.europe_pmc_client is not None
            if resources is not None
            else getattr(review_rerag_config, "enable_europe_pmc_fallback", False)
        ),
        pubtator_api_status=pubtator_api_status,
    )


CitationGraphServiceDep = Annotated[CitationGraphService, Depends(get_citation_graph_service)]
RelatedEvidenceServiceDep = Annotated[RelatedEvidenceService, Depends(get_related_evidence_service)]
TopicLiteratureMapServiceDep = Annotated[
    TopicLiteratureMapService,
    Depends(get_topic_literature_map_service),
]
CorpusSuggestionServiceDep = Annotated[
    CorpusSuggestionService, Depends(get_corpus_suggestion_service)
]
DiscoveryServiceDep = Annotated[DiscoveryService, Depends(get_discovery_service)]
DiagnosticsServiceDep = Annotated[DiagnosticsService, Depends(get_diagnostics_service)]
VariantEvidenceServiceDep = Annotated[
    VariantEvidenceService,
    Depends(get_variant_evidence_service),
]


async def _cleanup_discovery_dependencies() -> None:
    global _discovery_service, _ncbi_discovery_client
    global _citation_graph_service, _crossref_client, _europe_pmc_literature_client
    global _openalex_client, _unpaywall_client
    global _related_evidence_service, _topic_literature_map_service
    global _corpus_suggestion_service
    global _clinvar_service, _variant_evidence_service

    if _ncbi_discovery_client:
        ncbi_discovery_client = _ncbi_discovery_client
        _ncbi_discovery_client = None
        await ncbi_discovery_client.close()

    if _europe_pmc_literature_client:
        europe_pmc_literature_client = _europe_pmc_literature_client
        _europe_pmc_literature_client = None
        await europe_pmc_literature_client.close()

    if _openalex_client:
        openalex_client = _openalex_client
        _openalex_client = None
        await openalex_client.close()

    if _unpaywall_client:
        unpaywall_client = _unpaywall_client
        _unpaywall_client = None
        await unpaywall_client.close()

    if _crossref_client:
        crossref_client = _crossref_client
        _crossref_client = None
        await crossref_client.close()

    _corpus_suggestion_service = None
    _clinvar_service = None
    _variant_evidence_service = None
    _citation_graph_service = None
    _related_evidence_service = None
    _topic_literature_map_service = None
    _discovery_service = None
