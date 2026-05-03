from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Literal, cast

from pubtator_link.api.client import PubTator3Client
from pubtator_link.api.search_filters import merge_search_filters
from pubtator_link.config import text_processing_config
from pubtator_link.mcp.errors import mcp_field_validation_error
from pubtator_link.mcp.input_normalization import (
    attach_normalization_meta,
    normalize_retrieve_review_context_batch_args,
)
from pubtator_link.models.corpus_suggestion import CorpusSuggestionRequest
from pubtator_link.models.literature_graph import (
    PublicationCitationGraphRequest,
    RelatedEvidenceCandidatesRequest,
    TopicLiteratureMapRequest,
)
from pubtator_link.models.publication_metadata import PublicationMetadataRequest
from pubtator_link.models.publication_passages import (
    PublicationContextEstimateRequest,
    PublicationPassageMode,
    PublicationPassageRequest,
    Verbosity,
)
from pubtator_link.models.responses import (
    AnnotationEntity,
    EntityAutocompleteResponse,
    EntityMatch,
    PublicationExportResponse,
    RelatedEntity,
    RelationsResponse,
    TextAnnotationResultResponse,
    TextAnnotationSubmitResponse,
)
from pubtator_link.models.review_rerag import (
    BudgetStrategy,
    GroundQuestionResponse,
    IndexReviewEvidenceRequest,
    InspectReviewIndexRequest,
    McpReviewAuditBundleResponse,
    PrepareMode,
    RecordReviewContextRequest,
    RecordReviewContextResponse,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextBatchResponse,
    RetrieveReviewContextRequest,
    ReviewAuditTrailResponse,
    ReviewBatchResponseMode,
    ReviewLlmContext,
    ReviewLlmContextEventType,
    ReviewQuickstartResponse,
    ReviewTableMode,
    SampleSectionPolicy,
    StageResearchSessionRequest,
    UpsertEvidenceCertaintyRequest,
)
from pubtator_link.models.variants import VariantEvidenceRequest, VariantEvidenceSource
from pubtator_link.services.citation_graph import CitationGraphService
from pubtator_link.services.corpus_suggestion import CorpusSuggestionService
from pubtator_link.services.entity_matching import (
    matched_terms_from_match_text,
    synonyms_from_entity_item,
)
from pubtator_link.services.publication_metadata import PublicationMetadataService
from pubtator_link.services.publication_passage_service import PublicationPassageService
from pubtator_link.services.publication_service import PublicationService
from pubtator_link.services.related_evidence import RelatedEvidenceService
from pubtator_link.services.review_audit import ReviewAuditService
from pubtator_link.services.review_context_service import ReviewContextService
from pubtator_link.services.review_evidence_certainty import ReviewEvidenceCertaintyService
from pubtator_link.services.review_index_lifecycle import ReviewIndexLifecycleService
from pubtator_link.services.review_indexing import ReviewIndexingService
from pubtator_link.services.review_preparation_queue import ReviewPreparationQueue
from pubtator_link.services.search_coverage import (
    SearchCoverageMode,
    SearchCoveragePreflight,
    attach_preflight_coverage,
)
from pubtator_link.services.search_shaping import (
    IncludeCitations,
    SearchMetadataMode,
    SearchResponseMode,
    TextHighlightFormat,
    combined_search_text,
    selected_search_items,
    shaped_search_response,
)
from pubtator_link.services.source_preflight import SourcePreflightService
from pubtator_link.services.topic_literature_map import TopicLiteratureMapService

INLINE_AUDIT_BUNDLE_MAX_BYTES = 1_000_000
RESOURCE_LIST_LIMIT = 50
LiteratureGraphResponseModeArg = Literal["compact", "nodes_edges", "full"]
LiteratureGraphBias = Literal[
    "guideline",
    "cohort",
    "genotype_phenotype",
    "treatment",
    "pediatric",
    "population",
]


def _add_mcp_response_mode_warning(result: dict[str, Any]) -> dict[str, Any]:
    result.setdefault("_meta", {}).setdefault("warnings", []).append(
        {
            "provider": "mcp",
            "status": "response_mode_deprecation",
            "retryable": False,
            "message": (
                "Future MCP default will be response_mode='compact'; pass response_mode='full' "
                "for legacy nodes/edges arrays."
            ),
        }
    )
    return result


def _dump_mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        try:
            return cast(dict[str, Any], value.model_dump(mode="json"))
        except TypeError:
            return cast(dict[str, Any], value.model_dump())
    return dict(value)


def _bounded_mapping(value: Any, allowed_keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in allowed_keys if key in value}


def _bounded_list(
    values: Any, allowed_keys: set[str], *, limit: int = RESOURCE_LIST_LIMIT
) -> list[Any]:
    if not isinstance(values, list):
        return []
    bounded: list[Any] = []
    for value in values[:limit]:
        if isinstance(value, dict):
            bounded.append(_bounded_mapping(value, allowed_keys))
        else:
            bounded.append(value)
    return bounded


def _strip_resolver_trace(result: dict[str, Any]) -> dict[str, Any]:
    result.pop("resolver_attempts", None)
    for key in ("sources", "failed_sources", "results"):
        values = result.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict):
                    value.pop("resolver_attempts", None)
                    nested_sources = value.get("sources")
                    if isinstance(nested_sources, list):
                        for source in nested_sources:
                            if isinstance(source, dict):
                                source.pop("resolver_attempts", None)
    return result


async def search_biomedical_entities_impl(
    *,
    client: PubTator3Client,
    query: str,
    concept: (
        Literal["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine", "Phenotype"] | None
    ) = None,
    limit: int = 10,
) -> dict[str, Any]:
    normalized_query = query.strip()
    raw_response = await client.autocomplete_entity(
        query=normalized_query,
        concept=concept,
        limit=limit,
    )
    raw_results = cast(list[dict[str, Any]], raw_response)
    matches = [
        EntityMatch(
            identifier=item.get("_id", ""),
            name=item.get("name", ""),
            type=item.get("biotype", concept or "Unknown"),
            score=item.get("score"),
            synonyms=synonyms_from_entity_item(item),
            matched_terms=matched_terms_from_match_text(item.get("match")),
            db_id=item.get("db_id"),
            db=item.get("db"),
            match=item.get("match"),
        )
        for item in raw_results
    ]
    return EntityAutocompleteResponse(
        success=True,
        query=normalized_query,
        matches=matches,
        total_matches=len(matches),
        concept_filter=concept,
    ).model_dump()


async def fetch_publication_annotations_impl(
    *,
    service: PublicationService,
    pmids: list[str],
    format: Literal["pubtator", "biocxml", "biocjson"] = "biocjson",
    full: bool = False,
) -> dict[str, Any]:
    result = await service.export_publications_list(
        pmids=pmids,
        format=format,
        full=full,
    )
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return dict(result)


async def get_publication_passages_impl(
    *,
    service: PublicationPassageService,
    pmids: list[str],
    sections: list[str] | None = None,
    mode: PublicationPassageMode = "compact_passages",
    full: bool = False,
    max_passages_per_pmid: int = 6,
    max_chars: int = 12000,
    include_tables: bool = True,
    include_references: bool = False,
    dry_run: bool = False,
    verbosity: Verbosity = "standard",
) -> dict[str, Any]:
    response = await service.get_passages(
        PublicationPassageRequest(
            pmids=pmids,
            sections=sections or [],
            mode=mode,
            full=full,
            max_passages_per_pmid=max_passages_per_pmid,
            max_chars=max_chars,
            include_tables=include_tables,
            include_references=include_references,
            dry_run=dry_run,
            verbosity=verbosity,
        )
    )
    return response.model_dump()


async def get_publication_metadata_impl(
    *,
    service: PublicationMetadataService,
    pmids: list[str],
    include_mesh: bool = True,
    include_publication_types: bool = True,
    include_citations: Literal["none", "nlm", "bibtex", "both"] = "both",
    include_coverage: bool = True,
) -> dict[str, Any]:
    response = await service.get_metadata(
        PublicationMetadataRequest(
            pmids=pmids,
            include_mesh=include_mesh,
            include_publication_types=include_publication_types,
            include_citations=include_citations,
            include_coverage=include_coverage,
        )
    )
    return response.model_dump(by_alias=True)


async def get_publication_citation_graph_impl(
    *,
    service: CitationGraphService,
    pmid: str | None = None,
    doi: str | None = None,
    direction: Literal["references", "cited_by", "both"] = "both",
    response_mode: LiteratureGraphResponseModeArg | None = None,
    resolve_metadata: bool = True,
    resolve_reference_pmids: bool = True,
    max_reference_resolution: int = 20,
    include_provider_status: bool = True,
    include_open_access_status: bool = True,
    max_results: int = 50,
) -> dict[str, Any]:
    effective_response_mode = response_mode or "full"
    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            pmid=pmid,
            doi=doi,
            direction=direction,
            response_mode=effective_response_mode,
            resolve_metadata=resolve_metadata,
            resolve_reference_pmids=resolve_reference_pmids,
            max_reference_resolution=max_reference_resolution,
            include_provider_status=include_provider_status,
            include_open_access_status=include_open_access_status,
            max_results=max_results,
        )
    )
    result = response.model_dump(by_alias=True)
    if response_mode is None:
        _add_mcp_response_mode_warning(result)
    return result


async def find_related_evidence_candidates_impl(
    *,
    service: RelatedEvidenceService,
    pmid: str,
    max_results: int = 25,
    response_mode: LiteratureGraphResponseModeArg | None = None,
    prefer_full_text: bool = True,
    include_pubtator_search: bool = True,
    include_citation_neighbors: bool = True,
    publication_types: list[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
) -> dict[str, Any]:
    effective_response_mode = response_mode or "full"
    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid=pmid,
            max_results=max_results,
            response_mode=effective_response_mode,
            prefer_full_text=prefer_full_text,
            include_pubtator_search=include_pubtator_search,
            include_citation_neighbors=include_citation_neighbors,
            publication_types=publication_types,
            year_min=year_min,
            year_max=year_max,
        )
    )
    result = response.model_dump(by_alias=True)
    if response_mode is None:
        _add_mcp_response_mode_warning(result)
    return result


async def build_topic_literature_map_impl(
    *,
    service: TopicLiteratureMapService,
    query: str | None = None,
    pmids: list[str] | None = None,
    max_seed_papers: int = 25,
    max_neighbors_per_paper: int = 10,
    response_mode: LiteratureGraphResponseModeArg | None = None,
    max_candidates: int = 12,
    include_demoted: bool = True,
    max_demoted: int = 3,
    bias_toward: list[LiteratureGraphBias] | None = None,
    max_graph_nodes: int = 30,
    max_graph_edges: int = 60,
    include_authors: bool = True,
    include_citations: bool = True,
    include_pubtator_entities: bool = True,
    include_related_candidates: bool = True,
    year_min: int | None = None,
    year_max: int | None = None,
    prefer_full_text: bool = True,
) -> dict[str, Any]:
    effective_response_mode = response_mode or "full"
    response = await service.build_map(
        TopicLiteratureMapRequest(
            query=query,
            pmids=pmids,
            max_seed_papers=max_seed_papers,
            max_neighbors_per_paper=max_neighbors_per_paper,
            response_mode=effective_response_mode,
            max_candidates=max_candidates,
            include_demoted=include_demoted,
            max_demoted=max_demoted,
            bias_toward=bias_toward,
            max_graph_nodes=max_graph_nodes,
            max_graph_edges=max_graph_edges,
            include_authors=include_authors,
            include_citations=include_citations,
            include_pubtator_entities=include_pubtator_entities,
            include_related_candidates=include_related_candidates,
            year_min=year_min,
            year_max=year_max,
            prefer_full_text=prefer_full_text,
        )
    )
    result = response.model_dump(by_alias=True)
    if response_mode is None:
        _add_mcp_response_mode_warning(result)
    return result


async def suggest_corpus_impl(
    *,
    service: CorpusSuggestionService,
    question: str,
    max_pmids: int = 8,
    entity_ids: list[str] | None = None,
    must_include_pmids: list[str] | None = None,
    prefer_guidelines: bool = True,
    include_metadata: bool = True,
) -> dict[str, Any]:
    response = await service.suggest(
        CorpusSuggestionRequest(
            question=question,
            max_pmids=max_pmids,
            entity_ids=entity_ids or [],
            must_include_pmids=must_include_pmids or [],
            prefer_guidelines=prefer_guidelines,
            include_metadata=include_metadata,
        )
    )
    return response.model_dump(by_alias=True)


async def estimate_publication_context_impl(
    *,
    service: PublicationPassageService,
    pmids: list[str],
    sections: list[str] | None = None,
    mode: PublicationPassageMode = "compact_passages",
    full: bool = False,
    max_passages_per_pmid: int = 6,
    include_tables: bool = True,
    include_references: bool = False,
) -> dict[str, Any]:
    response = await service.estimate_context(
        PublicationContextEstimateRequest(
            pmids=pmids,
            sections=sections or [],
            mode=mode,
            full=full,
            max_passages_per_pmid=max_passages_per_pmid,
            include_tables=include_tables,
            include_references=include_references,
        )
    )
    return response.model_dump()


async def search_literature_impl(
    *,
    client: PubTator3Client,
    text: str,
    page: int = 1,
    sort: str | None = None,
    filters: str | None = None,
    publication_types: list[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    sections: list[str] | None = None,
    response_mode: SearchResponseMode = "compact",
    include_citations: IncludeCitations = "none",
    text_hl_format: TextHighlightFormat = "plain",
    limit: int | None = 5,
    entity_ids: list[str] | None = None,
    guideline_boost: bool = False,
    coverage: SearchCoverageMode = "none",
    preflight_service: SearchCoveragePreflight | None = None,
    metadata: SearchMetadataMode = "basic",
    metadata_service: PublicationMetadataService | None = None,
) -> dict[str, Any]:
    normalized_text = combined_search_text(text, entity_ids)
    merged_filters = merge_search_filters(
        filters=filters,
        publication_types=publication_types,
        year_min=year_min,
        year_max=year_max,
    )
    result = await client.search_publications(
        text=normalized_text,
        page=page,
        sort=sort,
        filters=merged_filters,
        sections=",".join(sections) if sections else None,
    )
    raw_items = _selected_search_items(
        result,
        limit=limit,
        guideline_boost=guideline_boost,
    )
    metadata_by_pmid = await _search_metadata_by_pmid(
        raw_items,
        metadata=metadata,
        include_citations=include_citations,
        metadata_service=metadata_service,
    )
    response = shaped_search_response(
        raw=result,
        query=normalized_text,
        page=page,
        sort=sort,
        filters=merged_filters,
        sections=sections,
        response_mode=response_mode,
        include_citations=include_citations,
        text_hl_format=text_hl_format,
        limit=limit,
        guideline_boost=guideline_boost,
        metadata=metadata,
        metadata_by_pmid=metadata_by_pmid,
    )
    response_meta = {
        "coverage_note": (
            "Search is read-only metadata discovery. Use coverage='preflight' or "
            "pubtator.preflight_review_sources before indexing if source coverage matters."
        ),
        "next_tools": [
            "pubtator.preflight_review_sources",
            "pubtator.index_review_evidence",
        ],
        "workflow": "search -> preflight -> index -> inspect -> retrieve",
        "details_resource": "pubtator://workflow-help",
    }
    if coverage == "preflight" and preflight_service is not None:
        await attach_preflight_coverage(response, preflight_service)
    dumped = response.model_dump()
    dumped["_meta"] = response_meta
    return dumped


def _selected_search_items(
    raw_result: dict[str, Any],
    *,
    limit: int | None,
    guideline_boost: bool,
) -> list[dict[str, Any]]:
    items = list(raw_result.get("results", []))
    return selected_search_items(items, guideline_boost=guideline_boost, limit=limit)


async def _search_metadata_by_pmid(
    raw_items: list[dict[str, Any]],
    *,
    metadata: SearchMetadataMode,
    include_citations: IncludeCitations,
    metadata_service: PublicationMetadataService | None,
) -> dict[str, dict[str, Any]]:
    if metadata == "none" or metadata_service is None:
        return {}
    pmids = [str(item.get("pmid", "")) for item in raw_items]
    pmids = [pmid for pmid in dict.fromkeys(pmids) if pmid]
    if not pmids:
        return {}
    include_metadata_citations: IncludeCitations = (
        "both" if metadata == "full" and include_citations == "none" else include_citations
    )
    response = await metadata_service.get_metadata(
        PublicationMetadataRequest(
            pmids=pmids,
            include_mesh=metadata == "full",
            include_publication_types=True,
            include_citations=include_metadata_citations if metadata == "full" else "none",
            include_coverage=False,
        )
    )
    return {item.pmid: item.model_dump() for item in response.metadata}


async def fetch_pmc_annotations_impl(
    *,
    service: PublicationService,
    pmcids: list[str],
    format: Literal["biocxml", "biocjson"] = "biocjson",
) -> dict[str, Any]:
    result = await service.export_pmc_publications_list(
        pmcids=pmcids,
        format=format,
    )
    documents = [
        document.model_dump() if hasattr(document, "model_dump") else dict(document)
        for document in result.documents
    ]
    return PublicationExportResponse(
        format=result.format,
        pmcids=pmcids,
        full_text=True,
        export_data={"documents": documents},
        count=len(pmcids),
    ).model_dump()


async def find_entity_relations_impl(
    *,
    client: PubTator3Client,
    entity_id: str,
    relation_type: str | None = None,
    target_entity_type: str | None = None,
) -> dict[str, Any]:
    raw_response = await client.find_relations(
        e1=entity_id,
        relation_type=relation_type,
        e2=target_entity_type,
    )
    relation_response = cast(Any, raw_response)
    api_results = cast(
        list[dict[str, Any]], relation_response if isinstance(relation_response, list) else []
    )
    related_entities = [
        RelatedEntity(
            entity_id=item.get("target", ""),
            entity_name=item.get("entity_name"),
            entity_type=item.get("entity_type"),
            relation_type=item.get("type", ""),
            confidence=item.get("confidence"),
            pmids=item.get("pmids", []),
            source=item.get("source"),
            target=item.get("target", ""),
            publications=item.get("publications"),
        )
        for item in api_results
    ]
    return RelationsResponse(
        success=True,
        primary_entity=entity_id,
        related_entities=related_entities,
        total_relations=len(related_entities),
        relation_filter=relation_type,
        entity_filter=target_entity_type,
    ).model_dump()


async def lookup_variant_evidence_impl(
    *,
    service: Any,
    gene: str,
    variant: str | None = None,
    protein: str | None = None,
    condition: str | None = None,
    sources: list[VariantEvidenceSource] | None = None,
    max_literature_pmids: int = 20,
    include_citations: bool = True,
) -> dict[str, Any]:
    request = VariantEvidenceRequest(
        gene=gene,
        variant=variant,
        protein=protein,
        condition=condition,
        sources=sources or ["clinvar", "pubtator"],
        max_literature_pmids=max_literature_pmids,
        include_citations=include_citations,
    )
    response = await service.lookup(request)
    return cast(dict[str, Any], response.model_dump())


async def submit_text_annotation_impl(
    *,
    client: PubTator3Client,
    text: str,
    bioconcepts: str = "Gene",
) -> dict[str, Any]:
    if bioconcepts.lower() == "all":
        selected_bioconcepts = list(text_processing_config.supported_bioconcepts)
    else:
        selected_bioconcepts = [item.strip() for item in bioconcepts.split(",") if item.strip()]

    invalid_bioconcepts = [
        bioconcept
        for bioconcept in selected_bioconcepts
        if bioconcept not in text_processing_config.supported_bioconcepts
    ]
    if invalid_bioconcepts:
        raise ValueError(
            f"Invalid bioconcept(s): {', '.join(invalid_bioconcepts)}. "
            f"Supported types: {', '.join(text_processing_config.supported_bioconcepts)}"
        )

    normalized_text = text.strip()
    session_id = await client.submit_text_annotation(
        text=normalized_text, bioconcept=selected_bioconcepts[0]
    )
    if len(normalized_text) < 1000:
        estimated_time = 15
    elif len(normalized_text) < 5000:
        estimated_time = 45
    else:
        estimated_time = 90

    return TextAnnotationSubmitResponse(
        success=True,
        session_id=session_id,
        status="submitted",
        bioconcepts=selected_bioconcepts,
        estimated_time=estimated_time,
        message="Text submitted for processing. Use session_id to retrieve results.",
    ).model_dump()


async def get_text_annotation_results_impl(
    *,
    client: PubTator3Client,
    session_id: str,
) -> dict[str, Any]:
    result = await client.retrieve_text_annotation(session_id=session_id)
    status = str(result.get("status", "unknown"))
    annotations = [
        AnnotationEntity(
            start=annotation.get("start", 0),
            end=annotation.get("end", 0),
            text=annotation.get("text", ""),
            entity_id=annotation.get("entity_id", ""),
            entity_type=annotation.get("entity_type", ""),
            confidence=annotation.get("confidence"),
        )
        for annotation in result.get("annotations", [])
    ]
    return TextAnnotationResultResponse(
        success=True,
        session_id=session_id,
        status=status,
        original_text=str(result.get("original_text", "")),
        bioconcept=str(result.get("bioconcept", "")),
        annotations=annotations,
        processing_time=result.get("processing_time"),
        message=(
            "Processing in progress. Please try again in a few moments."
            if status in {"processing", "submitted"}
            else None
        ),
    ).model_dump()


async def index_review_evidence_impl(
    *,
    queue: ReviewPreparationQueue,
    review_id: str,
    pmids: list[str] | None = None,
    curated_urls: list[str] | None = None,
    prepare_mode: PrepareMode = "selected",
    session_id: str | None = None,
    wait_for_completion: bool = False,
    wait_for_status: Literal["complete", "complete_or_partial", "terminal"] | None = None,
    timeout_ms: int = 0,
    dry_run: bool = False,
) -> dict[str, Any]:
    api_request = IndexReviewEvidenceRequest(
        pmids=pmids or [],
        curated_urls=curated_urls or [],
        prepare_mode=prepare_mode,
        session_id=session_id,
        wait_for_completion=wait_for_completion,
        wait_for_status=wait_for_status,
        timeout_ms=timeout_ms,
        dry_run=dry_run,
    )
    service = ReviewIndexingService(repository=queue.repository, queue=queue)
    response = await service.index_review_evidence(review_id, api_request)
    return response.model_dump()


async def preflight_review_sources_impl(
    *,
    service: SourcePreflightService,
    pmids: list[str],
) -> dict[str, Any]:
    hints = await service.preflight_pmids(pmids)
    return {
        "success": True,
        "coverage_hints": [hint.model_dump(mode="json") for hint in hints],
    }


async def stage_research_session_impl(
    *,
    service: Any,
    review_id: str,
    query: str | None = None,
    pmids: list[str] | None = None,
    session_id: str | None = None,
    page: int = 1,
    sort: str | None = None,
    filters: str | None = None,
    publication_types: list[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    sections: list[str] | None = None,
    max_candidates: int = 20,
    stage_full_text: bool = True,
) -> dict[str, Any]:
    response = await service.stage(
        review_id=review_id,
        request=StageResearchSessionRequest(
            session_id=session_id,
            query=query,
            pmids=pmids or [],
            page=page,
            sort=sort,
            filters=filters,
            publication_types=publication_types or [],
            year_min=year_min,
            year_max=year_max,
            sections=sections or [],
            max_candidates=max_candidates,
            stage_full_text=stage_full_text,
        ),
    )
    try:
        result = response.model_dump(by_alias=True)
    except TypeError:
        result = response.model_dump()
    return cast(dict[str, Any], result)


async def review_quickstart_impl(
    *,
    stage_service: Any,
    context_service: ReviewContextService,
    topic: str,
    n_pmids: int = 8,
    review_id: str | None = None,
    session_id: str | None = None,
    wait_until_ready: bool = False,
    timeout_ms: int = 0,
) -> dict[str, Any]:
    normalized_topic = topic.strip()
    selected_review_id = review_id or _quickstart_review_id(normalized_topic)
    staged = await stage_service.stage(
        review_id=selected_review_id,
        request=StageResearchSessionRequest(
            session_id=session_id,
            query=normalized_topic,
            max_candidates=n_pmids,
            stage_full_text=True,
        ),
    )
    manifest = staged.manifest
    inspect_response = await context_service.inspect_review_index(
        selected_review_id,
        InspectReviewIndexRequest(session_id=manifest.session_id),
    )
    preparation_status = inspect_response.preparation_status
    ready_to_retrieve = (
        inspect_response.totals.passage_count > 0
        or preparation_status.complete > 0
        or preparation_status.partial > 0
    )
    warnings: list[str] = []
    if wait_until_ready and not ready_to_retrieve:
        warnings.append(
            "quickstart queued sources but no passages are ready yet; poll inspect_review_index"
        )
    if timeout_ms and not ready_to_retrieve:
        warnings.append("quickstart does not block on indexing; use inspect_review_index to poll")
    response = ReviewQuickstartResponse(
        review_id=selected_review_id,
        session_id=manifest.session_id,
        topic=normalized_topic,
        selected_pmids=[candidate.pmid for candidate in manifest.candidates],
        coverage_summary=inspect_response.coverage_summary or manifest.coverage_summary,
        preparation_status=preparation_status,
        indexed_totals=inspect_response.totals,
        ready_to_retrieve=ready_to_retrieve,
        next_commands=[
            "pubtator.retrieve_review_context_batch"
            if ready_to_retrieve
            else "pubtator.inspect_review_index",
            "pubtator.retrieve_review_context_batch",
        ],
        warnings=warnings,
    )
    return response.model_dump(mode="json")


async def ground_question_impl(
    *,
    client: PubTator3Client,
    queue: ReviewPreparationQueue,
    context_service: ReviewContextService,
    question: str,
    max_pmids: int = 8,
    review_id: str | None = None,
    entity_ids: list[str] | None = None,
    guideline_boost: bool = True,
    wait_until_ready: bool = True,
    timeout_ms: int = 30_000,
    review_indexing_service_factory: Any = ReviewIndexingService,
) -> dict[str, Any]:
    normalized_question = question.strip()
    selected_review_id = review_id or _quickstart_review_id(normalized_question)
    search_result = await search_literature_impl(
        client=client,
        text=normalized_question,
        limit=max_pmids,
        entity_ids=entity_ids,
        guideline_boost=guideline_boost,
        response_mode="compact",
        include_citations="none",
        metadata="basic",
    )
    selected_pmids: list[str] = []
    for item in search_result.get("results", []):
        if not isinstance(item, dict):
            continue
        pmid = str(item.get("pmid") or "").strip()
        if pmid and pmid not in selected_pmids:
            selected_pmids.append(pmid)
        if len(selected_pmids) >= max_pmids:
            break
    search_total_results = int(search_result.get("total_results") or len(selected_pmids))

    if not selected_pmids:
        return GroundQuestionResponse(
            question=normalized_question,
            review_id=selected_review_id,
            selected_pmids=[],
            search_total_results=search_total_results,
            ready_to_retrieve=False,
            context=None,
            next_tools=["pubtator.search_literature"],
            recovery=["Refine the search query or provide candidate PMIDs explicitly."],
        ).model_dump(mode="json")

    try:
        indexing_service = _review_indexing_service_from_factory(
            review_indexing_service_factory,
            queue,
        )
        await indexing_service.index_review_evidence(
            selected_review_id,
            IndexReviewEvidenceRequest(
                pmids=selected_pmids,
                wait_for_completion=wait_until_ready,
                wait_for_status="complete_or_partial" if wait_until_ready else None,
                timeout_ms=timeout_ms,
            ),
        )
        inspect_response = await context_service.inspect_review_index(
            review_id=selected_review_id,
            request=InspectReviewIndexRequest(pmids=selected_pmids),
        )
        ready_to_retrieve = _ground_question_sources_ready(inspect_response, selected_pmids)
        context: RetrieveReviewContextBatchResponse | None = None
        recovery: list[str] = []
        if ready_to_retrieve:
            context = await context_service.retrieve_context_batch(
                review_id=selected_review_id,
                request=RetrieveReviewContextBatchRequest(
                    queries=[normalized_question],
                    pmids=selected_pmids,
                    entity_ids=entity_ids or [],
                    response_mode="compact",
                    max_total_passages=8,
                    max_response_chars=12000,
                    include_diagnostics=False,
                ),
            )
            next_tools = [
                "pubtator.record_review_context",
                "pubtator.get_review_audit_trail",
            ]
        else:
            recovery.append(
                "Indexing has not produced passages yet; inspect the review index and retry retrieval."
            )
            next_tools = [
                "pubtator.inspect_review_index",
                "pubtator.retrieve_review_context_batch",
            ]
    except Exception as exc:
        exc.pmids = selected_pmids  # type: ignore[attr-defined]
        raise

    return GroundQuestionResponse(
        question=normalized_question,
        review_id=selected_review_id,
        selected_pmids=selected_pmids,
        search_total_results=search_total_results,
        preparation_status=inspect_response.preparation_status,
        coverage_summary=inspect_response.coverage_summary,
        ready_to_retrieve=ready_to_retrieve,
        context=context,
        next_tools=next_tools,
        recovery=recovery,
    ).model_dump(mode="json")


def _ground_question_sources_ready(inspect_response: Any, selected_pmids: list[str]) -> bool:
    selected = set(selected_pmids)
    if not selected:
        return False
    ready_coverages = {"abstract_only", "full_text", "curated_url"}
    ready_pmids: set[str] = set()
    for source in getattr(inspect_response, "sources", []) or []:
        pmid = str(getattr(source, "pmid", "") or "").strip()
        coverage = str(getattr(source, "coverage", "") or "").strip()
        passage_count = int(getattr(source, "passage_count", 0) or 0)
        if pmid in selected and (passage_count > 0 or coverage in ready_coverages):
            ready_pmids.add(pmid)
    return bool(ready_pmids)


def _review_indexing_service_from_factory(factory: Any, queue: ReviewPreparationQueue) -> Any:
    try:
        return factory(repository=queue.repository, queue=queue)
    except TypeError:
        try:
            return factory(queue)
        except TypeError:
            return factory(queue=queue)


def _quickstart_review_id(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:48]
    if not slug:
        slug = "review"
    digest = hashlib.sha256(topic.encode("utf-8")).hexdigest()[:8]
    return f"quickstart-{slug}-{digest}"


async def get_research_session_status_impl(
    *, service: Any, review_id: str, session_id: str
) -> dict[str, Any]:
    result = (await service.get_status(review_id=review_id, session_id=session_id)).model_dump(
        by_alias=True
    )
    return cast(dict[str, Any], result)


async def list_research_sessions_impl(*, service: Any, review_id: str) -> dict[str, Any]:
    result = (await service.list_sessions(review_id=review_id)).model_dump(by_alias=True)
    return cast(dict[str, Any], result)


async def review_summary_resource_impl(*, service: Any, review_id: str) -> dict[str, Any]:
    response = _dump_mapping(await service.get_summary(review_id))
    return {
        "success": bool(response.get("success", True)),
        "review_id": review_id,
        "index": _bounded_mapping(
            response.get("index"),
            {
                "review_id",
                "created_at",
                "updated_at",
                "expires_at",
                "preparation_status",
                "pmid_count",
                "source_count",
                "passage_count",
                "failed_source_count",
                "approximate_bytes",
            },
        )
        if response.get("index") is not None
        else None,
    }


async def review_sessions_resource_impl(*, service: Any, review_id: str) -> dict[str, Any]:
    response = _dump_mapping(await service.list_sessions(review_id=review_id))
    return {
        "success": bool(response.get("success", True)),
        "review_id": review_id,
        "sessions": _bounded_list(
            response.get("sessions"),
            {
                "review_id",
                "session_id",
                "query",
                "created_at",
                "updated_at",
                "candidate_count",
                "preparation_status",
                "coverage_summary",
            },
        ),
    }


async def review_session_detail_resource_impl(
    *,
    service: Any,
    review_id: str,
    session_id: str,
) -> dict[str, Any]:
    response = _dump_mapping(await service.get_status(review_id=review_id, session_id=session_id))
    return {
        "success": bool(response.get("success", True)),
        "review_id": review_id,
        "session_id": session_id,
        "session": _bounded_mapping(
            response.get("manifest"),
            {
                "review_id",
                "session_id",
                "query",
                "created_at",
                "updated_at",
                "candidate_count",
                "candidates",
                "preparation_status",
                "coverage_summary",
            },
        ),
    }


async def review_passage_resource_impl(
    *,
    service: Any,
    review_id: str,
    passage_id: str,
    before: int | None = None,
    after: int | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    if before is not None or after is not None:
        response = _dump_mapping(
            await service.get_neighboring_passages(
                review_id=review_id,
                passage_id=passage_id,
                before=before or 0,
                after=after or 0,
                same_section=True,
                session_id=session_id,
                max_chars_per_passage=2200,
            )
        )
    else:
        response = _dump_mapping(
            await service.get_passages_by_id(
                review_id=review_id,
                passage_ids=[passage_id],
                session_id=session_id,
                max_chars_per_passage=2200,
            )
        )
    passages = _bounded_list(
        response.get("passages"),
        {
            "passage_id",
            "review_id",
            "source_id",
            "source_kind",
            "section",
            "text",
            "pmid",
            "pmcid",
            "doi",
            "url",
            "heading_path",
            "page",
            "entity_ids",
            "relation_types",
            "screening_status",
        },
        limit=3 if before is not None or after is not None else 1,
    )
    if before is not None or after is not None:
        return {
            "success": bool(response.get("success", True)),
            "review_id": review_id,
            "passage_id": passage_id,
            "passages": passages,
            "not_found": response.get("not_found", []),
        }
    return {
        "success": bool(response.get("success", True)),
        "review_id": review_id,
        "passage_id": passage_id,
        "passage": passages[0] if passages else None,
        "not_found": response.get("not_found", []),
    }


async def review_audit_resource_impl(*, service: Any, review_id: str) -> dict[str, Any]:
    get_resource_summary = getattr(service, "get_resource_summary", None)
    if get_resource_summary is not None:
        response = _dump_mapping(await get_resource_summary(review_id))
        return {
            "success": bool(response.get("success", True)),
            "review_id": review_id,
            "generated_at": response.get("generated_at"),
            "preparation_status": response.get("preparation_status"),
            "totals": response.get("totals"),
            "search_runs": _bounded_list(
                response.get("search_runs"),
                {"query", "filters", "source", "returned_count", "created_at"},
            ),
            "retrieval_runs": _bounded_list(
                response.get("retrieval_runs"),
                {"queries", "passage_ids", "created_at"},
            ),
        }

    response = _dump_mapping(
        await service.get_audit_trail(
            review_id=review_id,
            passage_ids=[],
            session_id=None,
            max_chars_per_passage=500,
        )
    )
    return {
        "success": bool(response.get("success", True)),
        "review_id": review_id,
        "items": _bounded_list(
            response.get("items"),
            {"passage_id", "stable_citation_key", "section", "quote", "char_count"},
        ),
        "audit_block": response.get("audit_block", ""),
    }


async def review_passage_audit_resource_impl(
    *,
    service: Any,
    review_id: str,
    passage_id: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    response = _dump_mapping(
        await service.get_audit_trail(
            review_id=review_id,
            passage_ids=[passage_id],
            session_id=session_id,
            max_chars_per_passage=500,
        )
    )
    return {
        "success": bool(response.get("success", True)),
        "review_id": review_id,
        "passage_id": passage_id,
        "items": _bounded_list(
            response.get("items"),
            {"passage_id", "stable_citation_key", "section", "quote", "char_count"},
        ),
        "audit_block": response.get("audit_block", ""),
    }


def _empty_llm_context_resource(review_id: str) -> dict[str, Any]:
    return {
        "context_id": None,
        "review_id": review_id,
        "session_id": None,
        "kind": "retrieval_context",
        "topic": None,
        "research_question": None,
        "question_hash": None,
        "request": {},
        "response_summary": {},
        "selected_pmids": [],
        "rejected_pmids": [],
        "preferred_entity_ids": [],
        "active_queries": [],
        "successful_queries": [],
        "failed_queries": [],
        "selected_passage_ids": [],
        "audit_passage_ids": [],
        "open_questions": [],
        "user_decisions": [],
        "last_next_commands": [],
        "stable_citation_keys": {},
        "cache_key": None,
        "token_estimate": None,
        "created_by": None,
        "created_at": None,
        "updated_at": None,
    }


async def review_llm_context_resource_impl(
    *,
    service: Any,
    review_id: str,
    latest: bool = False,
    session_id: str | None = None,
) -> dict[str, Any]:
    context = await service.get_latest_context(review_id, session_id=session_id)
    context_payload = (
        context.model_dump(mode="json")
        if isinstance(context, ReviewLlmContext)
        else _empty_llm_context_resource(review_id)
    )
    return {
        "success": True,
        "review_id": review_id,
        "latest": latest,
        "context": context_payload,
    }


async def record_review_context_impl(
    *,
    service: Any,
    review_id: str,
    event_type: ReviewLlmContextEventType,
    session_id: str | None = None,
    topic: str | None = None,
    research_question: str | None = None,
    question_hash: str | None = None,
    request: dict[str, Any] | None = None,
    response_summary: dict[str, Any] | None = None,
    selected_pmids: list[str] | None = None,
    rejected_pmids: list[str] | None = None,
    preferred_entity_ids: list[str] | None = None,
    active_queries: list[str] | None = None,
    successful_queries: list[str] | None = None,
    failed_queries: list[str] | None = None,
    selected_passage_ids: list[str] | None = None,
    audit_passage_ids: list[str] | None = None,
    open_questions: list[dict[str, Any]] | None = None,
    user_decisions: list[dict[str, Any]] | None = None,
    last_next_commands: list[dict[str, Any]] | None = None,
    stable_citation_keys: dict[str, str] | None = None,
    cache_key: str | None = None,
    token_estimate: int | None = None,
    summary: str | None = None,
    pmids: list[str] | None = None,
    passage_ids: list[str] | None = None,
    queries: list[str] | None = None,
    decision: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    response = await service.record_context(
        review_id,
        RecordReviewContextRequest(
            session_id=session_id,
            topic=topic,
            research_question=research_question,
            question_hash=question_hash,
            request=request or {},
            response_summary=response_summary or {},
            selected_pmids=selected_pmids or [],
            rejected_pmids=rejected_pmids or [],
            preferred_entity_ids=preferred_entity_ids or [],
            active_queries=active_queries or [],
            successful_queries=successful_queries or [],
            failed_queries=failed_queries or [],
            selected_passage_ids=selected_passage_ids or [],
            audit_passage_ids=audit_passage_ids or [],
            open_questions=open_questions or [],
            user_decisions=user_decisions or [],
            last_next_commands=last_next_commands or [],
            stable_citation_keys=stable_citation_keys or {},
            cache_key=cache_key,
            token_estimate=token_estimate,
            event_type=event_type,
            summary=summary,
            pmids=pmids or [],
            passage_ids=passage_ids or [],
            queries=queries or [],
            decision=decision,
            payload=payload or {},
            created_by=created_by,
        ),
    )
    if isinstance(response, RecordReviewContextResponse):
        return response.model_dump(mode="json")
    return _dump_mapping(response)


async def inspect_review_index_impl(
    *,
    service: ReviewContextService,
    review_id: str,
    pmids: list[str] | None = None,
    session_id: str | None = None,
    include_passage_samples: bool = False,
    sample_per_pmid: int = 2,
    min_sample_chars: int = 80,
    sample_section_policy: SampleSectionPolicy = "evidence_first",
    include_metadata: bool = False,
    metadata: Literal["basic", "full"] = "basic",
) -> dict[str, Any]:
    response = await service.inspect_review_index(
        review_id=review_id,
        request=InspectReviewIndexRequest(
            session_id=session_id,
            pmids=pmids or [],
            include_passage_samples=include_passage_samples,
            sample_per_pmid=sample_per_pmid,
            min_sample_chars=min_sample_chars,
            sample_section_policy=sample_section_policy,
            include_metadata=include_metadata,
            metadata=metadata,
        ),
    )
    return response.model_dump()


async def get_review_passages_by_id_impl(
    *,
    service: ReviewContextService,
    review_id: str,
    passage_ids: list[str],
    session_id: str | None = None,
    max_chars_per_passage: int = 2200,
) -> dict[str, Any]:
    response = await service.get_passages_by_id(
        review_id=review_id,
        passage_ids=passage_ids,
        session_id=session_id,
        max_chars_per_passage=max_chars_per_passage,
    )
    return response.model_dump()


async def get_review_audit_trail_impl(
    *,
    service: ReviewContextService,
    review_id: str,
    passage_ids: list[str],
    session_id: str | None = None,
    max_chars_per_passage: int = 500,
) -> dict[str, Any]:
    response: ReviewAuditTrailResponse = await service.get_audit_trail(
        review_id=review_id,
        passage_ids=passage_ids,
        session_id=session_id,
        max_chars_per_passage=max_chars_per_passage,
    )
    return response.model_dump(mode="json")


async def get_neighboring_review_passages_impl(
    *,
    service: ReviewContextService,
    review_id: str,
    passage_id: str,
    session_id: str | None = None,
    before: int = 1,
    after: int = 1,
    same_section: bool = True,
    max_chars_per_passage: int = 2200,
) -> dict[str, Any]:
    response = await service.get_neighboring_passages(
        review_id=review_id,
        passage_id=passage_id,
        before=before,
        after=after,
        same_section=same_section,
        session_id=session_id,
        max_chars_per_passage=max_chars_per_passage,
    )
    return response.model_dump()


async def export_review_audit_bundle_impl(
    *,
    service: ReviewAuditService,
    review_id: str,
    session_id: str | None = None,
    export_path: str | None = None,
    fallback_inline: bool = False,
) -> dict[str, Any]:
    bundle = await service.export_bundle(review_id, session_id=session_id)
    bundle_json = bundle.model_dump(mode="json")
    if export_path is None:
        return McpReviewAuditBundleResponse(audit_bundle=bundle).model_dump(
            mode="json",
            exclude_none=True,
        )

    output_path = Path(export_path).expanduser()
    serialized = json.dumps(bundle_json, separators=(",", ":"), sort_keys=True)
    field_error = _audit_export_path_error(output_path)
    if field_error is not None:
        if fallback_inline:
            return _inline_audit_bundle_or_error(
                bundle_json,
                len(serialized.encode("utf-8")),
                field_error=field_error,
            )
        return McpReviewAuditBundleResponse(
            success=False,
            error=field_error,
        ).model_dump(mode="json", exclude_none=True)

    try:
        with output_path.open("x", encoding="utf-8") as output_file:
            output_file.write(serialized)
    except FileExistsError:
        field_error = _audit_export_path_field_error("export path already exists")
    except IsADirectoryError:
        field_error = _audit_export_path_field_error("export path is a directory")
    except OSError:
        field_error = _audit_export_path_field_error("parent directory is not writable")

    if field_error is not None:
        if fallback_inline:
            return _inline_audit_bundle_or_error(
                bundle_json,
                len(serialized.encode("utf-8")),
                field_error=field_error,
            )
        return McpReviewAuditBundleResponse(
            success=False,
            error=field_error,
        ).model_dump(mode="json", exclude_none=True)

    return McpReviewAuditBundleResponse(export_path=str(output_path)).model_dump(
        mode="json",
        exclude_none=True,
    )


def _audit_export_path_error(output_path: Path) -> dict[str, Any] | None:
    if output_path.is_symlink():
        return _audit_export_path_field_error("export path is a symlink")
    if output_path.exists():
        if output_path.is_dir():
            return _audit_export_path_field_error("export path is a directory")
        return _audit_export_path_field_error("export path already exists")

    parent = output_path.parent
    if not parent.exists():
        return _audit_export_path_field_error("parent directory does not exist")
    if not parent.is_dir():
        return _audit_export_path_field_error("parent path is not a directory")
    if not os.access(parent, os.W_OK):
        return _audit_export_path_field_error("parent directory is not writable")
    return None


def _audit_export_path_field_error(reason: str) -> dict[str, Any]:
    return mcp_field_validation_error(
        field="export_path",
        reason=reason,
        recovery_hint="Use fallback_inline=True or choose a writable path.",
    )


def _inline_audit_bundle_or_error(
    bundle_json: dict[str, Any],
    serialized_size_bytes: int,
    *,
    field_error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if serialized_size_bytes > INLINE_AUDIT_BUNDLE_MAX_BYTES:
        error: dict[str, Any] = {
            "code": "export_unavailable",
            "recovery_hint": "Choose a writable export_path; the audit bundle is too large for inline JSON.",
        }
        if field_error is not None and "field_errors" in field_error:
            error["field_errors"] = field_error["field_errors"]
        return McpReviewAuditBundleResponse(
            success=False,
            error=error,
        ).model_dump(mode="json", exclude_none=True)
    response = McpReviewAuditBundleResponse(inline_bundle=bundle_json).model_dump(
        mode="json",
        exclude_none=True,
    )
    response["export_path"] = None
    return response


async def retrieve_review_context_impl(
    *,
    service: ReviewContextService,
    review_id: str,
    question: str,
    session_id: str | None = None,
    pmids: list[str] | None = None,
    entity_ids: list[str] | None = None,
    sections: list[str] | None = None,
    max_passages: int = 8,
    max_chars: int = 6000,
    include_diagnostics: bool = False,
    include_tables: bool = False,
    include_references: bool = False,
    table_mode: ReviewTableMode = "preview",
    section_policy: SampleSectionPolicy = "evidence_first",
    allow_truncated_passages: bool = True,
    max_chars_per_passage: int = 2200,
    include_resolver_trace: bool = False,
) -> dict[str, Any]:
    response = await service.retrieve_context(
        review_id=review_id,
        request=RetrieveReviewContextRequest(
            question=question,
            session_id=session_id,
            pmids=pmids or [],
            entity_ids=entity_ids or [],
            sections=sections or [],
            max_passages=max_passages,
            max_chars=max_chars,
            include_diagnostics=include_diagnostics,
            include_tables=include_tables,
            include_references=include_references,
            table_mode=table_mode,
            section_policy=section_policy,
            allow_truncated_passages=allow_truncated_passages,
            max_chars_per_passage=max_chars_per_passage,
        ),
    )
    result = response.model_dump()
    return result if include_resolver_trace else _strip_resolver_trace(result)


async def retrieve_review_context_batch_impl(
    *,
    service: ReviewContextService,
    review_id: str,
    queries: list[str] | str,
    query: str | None = None,
    question: str | None = None,
    session_id: str | None = None,
    pmids: list[str] | None = None,
    entity_ids: list[str] | None = None,
    sections: list[str] | None = None,
    response_mode: ReviewBatchResponseMode | str = "compact",
    max_passages_per_query: int = 8,
    max_total_passages: int | None = None,
    limit: int | None = None,
    size: int | None = None,
    max_chars: int = 12000,
    max_response_chars: int = 24000,
    deduplicate_passages: bool = True,
    budget_strategy: BudgetStrategy | str = "query_fair",
    min_passages_per_source: int = 1,
    min_passages_per_pmid: int = 0,
    prioritize_pmids: list[str] | str | None = None,
    include_diagnostics: bool = False,
    include_tables: bool = False,
    include_references: bool = False,
    table_mode: ReviewTableMode | str = "preview",
    section_policy: SampleSectionPolicy | str = "evidence_first",
    allow_truncated_passages: bool = True,
    max_chars_per_passage: int = 2200,
    dry_run: bool = False,
    include_resolver_trace: bool = False,
) -> dict[str, Any]:
    args: dict[str, Any] = {
        "review_id": review_id,
        "queries": queries,
        "query": query,
        "question": question,
        "session_id": session_id,
        "pmids": pmids,
        "entity_ids": entity_ids,
        "sections": sections,
        "response_mode": response_mode,
        "max_passages_per_query": max_passages_per_query,
        "max_total_passages": max_total_passages,
        "limit": limit,
        "size": size,
        "max_chars": max_chars,
        "max_response_chars": max_response_chars,
        "deduplicate_passages": deduplicate_passages,
        "budget_strategy": budget_strategy,
        "min_passages_per_source": min_passages_per_source,
        "min_passages_per_pmid": min_passages_per_pmid,
        "prioritize_pmids": prioritize_pmids,
        "include_diagnostics": include_diagnostics,
        "include_tables": include_tables,
        "include_references": include_references,
        "table_mode": table_mode,
        "section_policy": section_policy,
        "allow_truncated_passages": allow_truncated_passages,
        "max_chars_per_passage": max_chars_per_passage,
        "dry_run": dry_run,
    }
    args = {key: value for key, value in args.items() if value is not None}
    normalized_args, normalization_warnings = normalize_retrieve_review_context_batch_args(args)
    request_args = {
        "queries": normalized_args["queries"],
        "session_id": normalized_args.get("session_id"),
        "pmids": normalized_args.get("pmids") or [],
        "entity_ids": normalized_args.get("entity_ids") or [],
        "sections": normalized_args.get("sections") or [],
        "response_mode": normalized_args["response_mode"],
        "max_passages_per_query": normalized_args["max_passages_per_query"],
        "max_total_passages": normalized_args.get("max_total_passages", 20),
        "max_chars": normalized_args["max_chars"],
        "max_response_chars": normalized_args["max_response_chars"],
        "deduplicate_passages": normalized_args["deduplicate_passages"],
        "budget_strategy": normalized_args["budget_strategy"],
        "min_passages_per_source": normalized_args["min_passages_per_source"],
        "min_passages_per_pmid": normalized_args["min_passages_per_pmid"],
        "prioritize_pmids": normalized_args.get("prioritize_pmids") or [],
        "include_diagnostics": normalized_args["include_diagnostics"],
        "include_tables": normalized_args["include_tables"],
        "include_references": normalized_args["include_references"],
        "table_mode": normalized_args["table_mode"],
        "section_policy": normalized_args.get("section_policy", "evidence_first"),
        "allow_truncated_passages": normalized_args["allow_truncated_passages"],
        "max_chars_per_passage": normalized_args["max_chars_per_passage"],
        "dry_run": normalized_args["dry_run"],
    }
    request = RetrieveReviewContextBatchRequest(**request_args)
    response = await service.retrieve_context_batch(
        review_id=review_id,
        request=request,
    )
    result = response.model_dump()
    if not include_resolver_trace:
        result = _strip_resolver_trace(result)
    return attach_normalization_meta(result, normalization_warnings)


async def list_review_indexes_impl(
    *,
    service: ReviewIndexLifecycleService,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    response = await service.list_indexes(limit=limit, offset=offset)
    return response.model_dump(mode="json")


async def get_review_index_summary_impl(
    *,
    service: ReviewIndexLifecycleService,
    review_id: str,
) -> dict[str, Any]:
    response = await service.get_summary(review_id)
    return response.model_dump(mode="json")


async def add_evidence_certainty_impl(
    *,
    service: ReviewEvidenceCertaintyService,
    review_id: str,
    outcome: str,
    question: str | None = None,
    study_design: str | None = None,
    risk_of_bias_notes: str | None = None,
    inconsistency_notes: str | None = None,
    indirectness_notes: str | None = None,
    imprecision_notes: str | None = None,
    publication_bias_notes: str | None = None,
    overall_certainty: str = "not_rated",
    certainty_rationale: str | None = None,
    passage_ids: list[str] | None = None,
    created_by: str | None = None,
    validate_passages: bool = False,
) -> dict[str, Any]:
    response = await service.upsert(
        review_id,
        UpsertEvidenceCertaintyRequest(
            outcome=outcome,
            question=question,
            study_design=study_design,
            risk_of_bias_notes=risk_of_bias_notes,
            inconsistency_notes=inconsistency_notes,
            indirectness_notes=indirectness_notes,
            imprecision_notes=imprecision_notes,
            publication_bias_notes=publication_bias_notes,
            overall_certainty=overall_certainty,  # type: ignore[arg-type]
            certainty_rationale=certainty_rationale,
            passage_ids=passage_ids or [],
            created_by=created_by,
            validate_passages=validate_passages,
        ),
    )
    return response.model_dump(mode="json")


async def list_evidence_certainty_impl(
    *,
    service: ReviewEvidenceCertaintyService,
    review_id: str,
) -> dict[str, Any]:
    response = await service.list(review_id)
    return response.model_dump(mode="json")


async def get_evidence_certainty_impl(
    *,
    service: ReviewEvidenceCertaintyService,
    review_id: str,
    certainty_id: str,
) -> dict[str, Any]:
    response = await service.get(review_id, certainty_id)
    return response.model_dump(mode="json")
