from __future__ import annotations

from typing import Any, Literal, cast

from pubtator_link.api.client import PubTator3Client
from pubtator_link.api.search_filters import merge_search_filters
from pubtator_link.config import text_processing_config
from pubtator_link.models.publication_passages import (
    PublicationContextEstimateRequest,
    PublicationPassageMode,
    PublicationPassageRequest,
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
    ReviewBatchResponseMode,
    ReviewTableMode,
    StageResearchSessionRequest,
    UpsertEvidenceCertaintyRequest,
)
from pubtator_link.services.entity_matching import matched_terms_from_match_text
from pubtator_link.services.publication_passage_service import PublicationPassageService
from pubtator_link.services.publication_service import PublicationService
from pubtator_link.services.review_audit import ReviewAuditService
from pubtator_link.services.review_context_service import ReviewContextService
from pubtator_link.services.review_evidence_certainty import ReviewEvidenceCertaintyService
from pubtator_link.services.review_index_lifecycle import ReviewIndexLifecycleService
from pubtator_link.services.review_preparation_queue import ReviewPreparationQueue
from pubtator_link.services.search_shaping import (
    IncludeCitations,
    SearchResponseMode,
    TextHighlightFormat,
    combined_search_text,
    shaped_search_response,
)
from pubtator_link.services.source_preflight import SourcePreflightService


async def search_biomedical_entities_impl(
    *,
    client: PubTator3Client,
    query: str,
    concept: Literal["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine"] | None = None,
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
            synonyms=item.get("synonyms", []),
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
        )
    )
    return response.model_dump()


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
    )
    return response.model_dump()


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
) -> dict[str, Any]:
    api_request = IndexReviewEvidenceRequest(
        pmids=pmids or [],
        curated_urls=curated_urls or [],
        prepare_mode=prepare_mode,
    )
    queued = 0
    already_prepared = 0
    for pmid in api_request.pmids:
        if await queue.enqueue_pmid(review_id, pmid):
            queued += 1
        else:
            already_prepared += 1
    for url in api_request.curated_urls:
        if await queue.enqueue_curated_url(review_id, url):
            queued += 1
        else:
            already_prepared += 1
    status = await queue.repository.preparation_status(review_id)
    response = {
        "success": True,
        "review_id": review_id,
        "queued": queued,
        "already_prepared": already_prepared,
        "preparation_status": status.model_dump(),
        "retry_after_ms": 5000 if status.queued or status.running else None,
        "lifecycle_note": (
            "Repeated calls with the same review_id and already prepared PMIDs are no-ops "
            "counted as already_prepared; new PMIDs are enqueued for the same review_id. "
            "Call pubtator.inspect_review_index for source coverage, failed sources, and "
            "passage counts before retrieval."
        ),
    }
    return response


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
    include_passage_samples: bool = False,
    sample_per_pmid: int = 2,
) -> dict[str, Any]:
    response = await service.inspect_review_index(
        review_id=review_id,
        request=InspectReviewIndexRequest(
            pmids=pmids or [],
            include_passage_samples=include_passage_samples,
            sample_per_pmid=sample_per_pmid,
        ),
    )
    return response.model_dump()


async def get_review_passages_by_id_impl(
    *,
    service: ReviewContextService,
    review_id: str,
    passage_ids: list[str],
    max_chars_per_passage: int = 2200,
) -> dict[str, Any]:
    response = await service.get_passages_by_id(
        review_id=review_id,
        passage_ids=passage_ids,
        max_chars_per_passage=max_chars_per_passage,
    )
    return response.model_dump()


async def get_neighboring_review_passages_impl(
    *,
    service: ReviewContextService,
    review_id: str,
    passage_id: str,
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
        max_chars_per_passage=max_chars_per_passage,
    )
    return response.model_dump()


async def export_review_audit_bundle_impl(
    *,
    service: ReviewAuditService,
    review_id: str,
) -> dict[str, Any]:
    bundle = await service.export_bundle(review_id)
    return McpReviewAuditBundleResponse(audit_bundle=bundle).model_dump(mode="json")


async def retrieve_review_context_impl(
    *,
    service: ReviewContextService,
    review_id: str,
    question: str,
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
) -> dict[str, Any]:
    response = await service.retrieve_context(
        review_id=review_id,
        request=RetrieveReviewContextRequest(
            question=question,
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
    return response.model_dump()


async def retrieve_review_context_batch_impl(
    *,
    service: ReviewContextService,
    review_id: str,
    queries: list[str],
    pmids: list[str] | None = None,
    entity_ids: list[str] | None = None,
    sections: list[str] | None = None,
    response_mode: ReviewBatchResponseMode = "compact",
    max_passages_per_query: int = 8,
    max_total_passages: int = 20,
    max_chars: int = 12000,
    max_response_chars: int = 24000,
    deduplicate_passages: bool = True,
    budget_strategy: BudgetStrategy = "query_fair",
    min_passages_per_source: int = 1,
    include_diagnostics: bool = True,
    include_tables: bool = False,
    include_references: bool = False,
    table_mode: ReviewTableMode = "preview",
    allow_truncated_passages: bool = True,
    max_chars_per_passage: int = 2200,
) -> dict[str, Any]:
    response = await service.retrieve_context_batch(
        review_id=review_id,
        request=RetrieveReviewContextBatchRequest(
            queries=queries,
            pmids=pmids or [],
            entity_ids=entity_ids or [],
            sections=sections or [],
            response_mode=response_mode,
            max_passages_per_query=max_passages_per_query,
            max_total_passages=max_total_passages,
            max_chars=max_chars,
            max_response_chars=max_response_chars,
            deduplicate_passages=deduplicate_passages,
            budget_strategy=budget_strategy,
            min_passages_per_source=min_passages_per_source,
            include_diagnostics=include_diagnostics,
            include_tables=include_tables,
            include_references=include_references,
            table_mode=table_mode,
            allow_truncated_passages=allow_truncated_passages,
            max_chars_per_passage=max_chars_per_passage,
        ),
    )
    return response.model_dump()


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
