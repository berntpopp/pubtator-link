from __future__ import annotations

import hashlib
import re
from typing import Any, Literal, cast

from pubtator_link.api.client import PubTator3Client
from pubtator_link.api.search_filters import merge_search_filters
from pubtator_link.config import text_processing_config
from pubtator_link.mcp.input_normalization import (
    attach_normalization_meta,
    normalize_retrieve_review_context_batch_args,
)
from pubtator_link.models.corpus_suggestion import CorpusSuggestionRequest
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
    IndexReviewEvidenceRequest,
    InspectReviewIndexRequest,
    McpReviewAuditBundleResponse,
    PrepareMode,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextRequest,
    ReviewAuditTrailResponse,
    ReviewBatchResponseMode,
    ReviewQuickstartResponse,
    ReviewTableMode,
    SampleSectionPolicy,
    StageResearchSessionRequest,
    UpsertEvidenceCertaintyRequest,
)
from pubtator_link.models.variants import VariantEvidenceRequest, VariantEvidenceSource
from pubtator_link.services.corpus_suggestion import CorpusSuggestionService
from pubtator_link.services.entity_matching import (
    matched_terms_from_match_text,
    synonyms_from_entity_item,
)
from pubtator_link.services.publication_metadata import PublicationMetadataService
from pubtator_link.services.publication_passage_service import PublicationPassageService
from pubtator_link.services.publication_service import PublicationService
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
    candidate_pmids = [item.pmid for item in response.results]
    response_meta = {
        "coverage_note": (
            "Search is read-only metadata discovery. Use coverage='preflight' or "
            "pubtator.preflight_review_sources before indexing if source coverage matters."
        ),
        "next_commands": [
            {
                "tool": "pubtator.preflight_review_sources",
                "arguments": {"pmids": candidate_pmids},
            },
            {
                "tool": "pubtator.index_review_evidence",
                "arguments": {"review_id": "<review_id>", "pmids": candidate_pmids},
                "requires": ["review_id"],
            },
        ],
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
) -> dict[str, Any]:
    bundle = await service.export_bundle(review_id, session_id=session_id)
    return McpReviewAuditBundleResponse(audit_bundle=bundle).model_dump(mode="json")


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
    include_diagnostics: bool = True,
    include_tables: bool = False,
    include_references: bool = False,
    table_mode: ReviewTableMode | str = "preview",
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
        "allow_truncated_passages": normalized_args["allow_truncated_passages"],
        "max_chars_per_passage": normalized_args["max_chars_per_passage"],
        "dry_run": normalized_args["dry_run"],
    }
    if request_args["response_mode"] == "quotes":
        validated_request = RetrieveReviewContextBatchRequest(
            **{**request_args, "response_mode": "compact"}
        )
        # Task 4 stages the quotes mode before the shared model enum is widened.
        request = validated_request.model_copy(update={"response_mode": "quotes"})
    else:
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
