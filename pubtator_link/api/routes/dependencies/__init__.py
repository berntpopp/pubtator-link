"""Aggregated re-exports for backward-compatible imports.

This module preserves the legacy import surface
`pubtator_link.api.routes.dependencies.<name>` after the 2026-05-26 split.
See docs/superpowers/plans/2026-05-26-phase-1-hosted-mcp-ship-blockers.md.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

from . import core_api as _core_api
from . import discovery as _discovery
from . import resources as _resources
from . import review as _review
from .core_api import (
    ClientDep as ClientDep,
)
from .core_api import (
    LoggerDep as LoggerDep,
)
from .core_api import (
    PublicationMetadataServiceDep as PublicationMetadataServiceDep,
)
from .core_api import (
    PublicationPassageServiceDep as PublicationPassageServiceDep,
)
from .core_api import (
    PublicationServiceDep as PublicationServiceDep,
)
from .core_api import (
    get_api_client,
    get_logger,
    get_publication_metadata_service,
    get_publication_passage_service,
    get_publication_service,
)
from .discovery import (
    CitationGraphServiceDep as CitationGraphServiceDep,
)
from .discovery import (
    CorpusSuggestionServiceDep as CorpusSuggestionServiceDep,
)
from .discovery import (
    DiscoveryServiceDep as DiscoveryServiceDep,
)
from .discovery import (
    RelatedEvidenceServiceDep as RelatedEvidenceServiceDep,
)
from .discovery import (
    TopicLiteratureMapServiceDep as TopicLiteratureMapServiceDep,
)
from .discovery import (
    VariantEvidenceServiceDep as VariantEvidenceServiceDep,
)
from .discovery import (
    get_citation_graph_service,
    get_clinvar_service,
    get_corpus_suggestion_service,
    get_diagnostics_service,
    get_discovery_service,
    get_related_evidence_service,
    get_topic_literature_map_service,
    get_variant_evidence_service,
)
from .resources import (
    AppResources,
    bind_app_resources,
    close_app_resources,
    create_app_resources,
    current_app_resources,
    reset_app_resources,
    resources_from_request,
    review_pool_kwargs,
)
from .review import (
    LlmReviewContextServiceDep as LlmReviewContextServiceDep,
)
from .review import (
    ResearchSessionServiceDep as ResearchSessionServiceDep,
)
from .review import (
    ReviewAuditServiceDep as ReviewAuditServiceDep,
)
from .review import (
    ReviewContextServiceDep as ReviewContextServiceDep,
)
from .review import (
    ReviewEvidenceCertaintyServiceDep as ReviewEvidenceCertaintyServiceDep,
)
from .review import (
    ReviewIndexLifecycleServiceDep as ReviewIndexLifecycleServiceDep,
)
from .review import (
    ReviewQueueDep as ReviewQueueDep,
)
from .review import (
    SourcePreflightServiceDep as SourcePreflightServiceDep,
)
from .review import (
    get_llm_review_context_service,
    get_research_session_service,
    get_review_audit_service,
    get_review_context_service,
    get_review_evidence_certainty_service,
    get_review_index_lifecycle_service,
    get_review_pool,
    get_review_queue,
    get_review_repository,
    get_source_preflight_service,
)
from .validation import (
    cleanup_dependencies,
    create_error_response,
    handle_api_errors,
    validate_entity_id,
    validate_limit,
    validate_page_number,
    validate_pmcids,
    validate_pmids,
)

_LEGACY_PRIVATE_EXPORTS = {
    "_api_client": _core_api,
    "_publication_service": _core_api,
    "_publication_passage_service": _core_api,
    "_publication_metadata_service": _core_api,
    "_ncbi_publication_metadata_client": _core_api,
    "_logger": _core_api,
    "_ncbi_discovery_client": _discovery,
    "_discovery_service": _discovery,
    "_crossref_client": _discovery,
    "_europe_pmc_literature_client": _discovery,
    "_openalex_client": _discovery,
    "_unpaywall_client": _discovery,
    "_citation_graph_service": _discovery,
    "_related_evidence_service": _discovery,
    "_topic_literature_map_service": _discovery,
    "_diagnostics_service": _discovery,
    "_corpus_suggestion_service": _discovery,
    "_clinvar_service": _discovery,
    "_variant_evidence_service": _discovery,
    "_review_pool": _review,
    "_review_repository": _review,
    "_review_queue": _review,
    "_review_context_service": _review,
    "_llm_review_context_service": _review,
    "_review_audit_service": _review,
    "_review_evidence_certainty_service": _review,
    "_review_index_lifecycle_service": _review,
    "_source_preflight_service": _review,
    "_research_session_service": _review,
}

_LEGACY_MUTABLE_EXPORTS = {
    **{name: (module,) for name, module in _LEGACY_PRIVATE_EXPORTS.items()},
    "asyncpg": (_resources, _review),
    "apply_migrations": (_resources,),
    "FullTextPreparationService": (_review,),
    "inspect_review_schema": (_resources, _discovery),
    "PostgresReviewReragRepository": (_resources, _review),
    "PublicationPassageService": (_resources, _core_api),
    "PublicationService": (_resources, _core_api),
    "PubTator3Client": (_resources, _core_api, _discovery, _review),
    "ReviewContextService": (_resources, _review),
    "review_rerag_config": (_resources, _discovery, _review),
    "ReviewPreparationQueue": (_resources, _review),
    "SentenceTransformerEmbeddingProvider": (_review,),
    "_build_full_text_preparation": (_review,),
    "_build_review_context_service": (_review,),
}


def __getattr__(name: str) -> Any:
    if name in _LEGACY_MUTABLE_EXPORTS:
        return getattr(_LEGACY_MUTABLE_EXPORTS[name][0], name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _DependenciesModule(ModuleType):
    def __getattribute__(self, name: str) -> Any:
        if name in {
            "_LEGACY_MUTABLE_EXPORTS",
            "__dict__",
            "__class__",
            "__name__",
            "__spec__",
            "__loader__",
            "__package__",
        }:
            return super().__getattribute__(name)
        exports = super().__getattribute__("_LEGACY_MUTABLE_EXPORTS")
        if name in exports:
            return getattr(exports[name][0], name)
        return super().__getattribute__(name)

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        for module in _LEGACY_MUTABLE_EXPORTS.get(name, ()):
            setattr(module, name, value)


sys.modules[__name__].__class__ = _DependenciesModule


__all__ = [
    "AppResources",
    "bind_app_resources",
    "cleanup_dependencies",
    "close_app_resources",
    "create_app_resources",
    "create_error_response",
    "current_app_resources",
    "get_api_client",
    "get_citation_graph_service",
    "get_clinvar_service",
    "get_corpus_suggestion_service",
    "get_diagnostics_service",
    "get_discovery_service",
    "get_llm_review_context_service",
    "get_logger",
    "get_publication_metadata_service",
    "get_publication_passage_service",
    "get_publication_service",
    "get_related_evidence_service",
    "get_research_session_service",
    "get_review_audit_service",
    "get_review_context_service",
    "get_review_evidence_certainty_service",
    "get_review_index_lifecycle_service",
    "get_review_pool",
    "get_review_queue",
    "get_review_repository",
    "get_source_preflight_service",
    "get_topic_literature_map_service",
    "get_variant_evidence_service",
    "handle_api_errors",
    "reset_app_resources",
    "resources_from_request",
    "review_pool_kwargs",
    "validate_entity_id",
    "validate_limit",
    "validate_page_number",
    "validate_pmcids",
    "validate_pmids",
]
