"""Lock down the public callable surface of api.routes.dependencies."""

from __future__ import annotations

import pubtator_link.api.routes.dependencies as deps

EXPECTED = {
    "AppResources",
    "bind_app_resources",
    "reset_app_resources",
    "current_app_resources",
    "resources_from_request",
    "review_pool_kwargs",
    "create_app_resources",
    "close_app_resources",
    "get_logger",
    "get_api_client",
    "get_publication_service",
    "get_publication_passage_service",
    "get_publication_metadata_service",
    "get_discovery_service",
    "get_citation_graph_service",
    "get_related_evidence_service",
    "get_topic_literature_map_service",
    "get_clinvar_service",
    "get_variant_evidence_service",
    "get_diagnostics_service",
    "get_corpus_suggestion_service",
    "get_review_pool",
    "get_review_repository",
    "get_review_queue",
    "get_review_context_service",
    "get_source_preflight_service",
    "get_review_audit_service",
    "get_llm_review_context_service",
    "get_review_index_lifecycle_service",
    "get_review_evidence_certainty_service",
    "get_research_session_service",
    "handle_api_errors",
    "create_error_response",
    "validate_pmids",
    "validate_pmcids",
    "validate_entity_id",
    "validate_page_number",
    "validate_limit",
    "cleanup_dependencies",
}

TOLERATED_LEGACY_CALLABLES = {
    "Annotated",
    "Any",
    "Callable",
    "CitationGraphService",
    "CitationGraphServiceDep",
    "ClientDep",
    "ClinVarService",
    "ContextVar",
    "CorpusSuggestionService",
    "CorpusSuggestionServiceDep",
    "CoverageReason",
    "CoverageTier",
    "CrossrefClient",
    "Depends",
    "DiagnosticsService",
    "DiscoveryService",
    "DiscoveryServiceDep",
    "EmbeddingProvider",
    "EmbeddingProviderUnavailableError",
    "EuropePmcClient",
    "EuropePmcLiteratureClient",
    "FilteringBoundLogger",
    "FullTextPreparationService",
    "HTTPException",
    "LlmReviewContextService",
    "LlmReviewContextServiceDep",
    "LoggerDep",
    "NcbiDiscoveryClient",
    "NcbiPublicationMetadataClient",
    "OpenAlexClient",
    "PostgresReviewReragRepository",
    "PubTator3Client",
    "PublicationMetadataService",
    "PublicationMetadataServiceDep",
    "PublicationPassageService",
    "PublicationPassageServiceDep",
    "PublicationService",
    "PublicationServiceDep",
    "RelatedEvidenceService",
    "RelatedEvidenceServiceDep",
    "Request",
    "ResearchSessionSearchProvider",
    "ResearchSessionService",
    "ResearchSessionServiceDep",
    "ReviewAuditService",
    "ReviewAuditServiceDep",
    "ReviewContextService",
    "ReviewContextServiceDep",
    "ReviewEvidenceCertaintyService",
    "ReviewEvidenceCertaintyServiceDep",
    "ReviewIndexLifecycleService",
    "ReviewIndexLifecycleServiceDep",
    "ReviewPreparationQueue",
    "ReviewQueueDep",
    "ReviewSchemaDiagnostics",
    "ReviewSchemaStaleError",
    "SearchResponse",
    "SearchResult",
    "SentenceTransformerEmbeddingProvider",
    "SourcePreflightService",
    "SourcePreflightServiceDep",
    "StageResearchSessionRequest",
    "Token",
    "TopicLiteratureMapService",
    "TopicLiteratureMapServiceDep",
    "UnpaywallClient",
    "VariantEvidenceService",
    "VariantEvidenceServiceDep",
    "apply_migrations",
    "configure_logging",
    "dataclass",
    "inspect_review_schema",
    "merge_search_filters",
}


def test_every_expected_name_is_importable_from_root() -> None:
    missing = sorted(name for name in EXPECTED if not hasattr(deps, name))
    assert not missing, f"missing re-exports: {missing}"


def test_no_unexpected_public_callables_were_added() -> None:
    public = {
        name
        for name in dir(deps)
        if not name.startswith("_") and callable(getattr(deps, name, None))
    }
    extra = public - EXPECTED
    extra -= {"asyncpg", "logger"}
    extra -= TOLERATED_LEGACY_CALLABLES
    assert not extra, f"unexpected public exports: {sorted(extra)}"
