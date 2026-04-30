from __future__ import annotations

from typing import Any, cast

from pubtator_link.api.client import PubTator3Client
from pubtator_link.config import text_processing_config
from pubtator_link.mcp.tools import (
    EstimatePublicationContextMcpRequest,
    FetchPmcAnnotationsRequest,
    FetchPublicationAnnotationsRequest,
    FindEntityRelationsRequest,
    GetPublicationPassagesMcpRequest,
    GetTextAnnotationResultsRequest,
    IndexReviewEvidenceMcpRequest,
    InspectReviewIndexMcpRequest,
    RetrieveReviewContextBatchMcpRequest,
    RetrieveReviewContextMcpRequest,
    SearchBiomedicalEntitiesRequest,
    SearchLiteratureRequest,
    SubmitTextAnnotationRequest,
)
from pubtator_link.models.publication_passages import (
    PublicationContextEstimateRequest,
    PublicationPassageRequest,
)
from pubtator_link.models.responses import (
    AnnotationEntity,
    EntityAutocompleteResponse,
    EntityMatch,
    PublicationExportResponse,
    RelatedEntity,
    RelationsResponse,
    SearchResponse,
    SearchResult,
    TextAnnotationResultResponse,
    TextAnnotationSubmitResponse,
)
from pubtator_link.models.review_rerag import (
    IndexReviewEvidenceRequest,
    InspectReviewIndexRequest,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextRequest,
)
from pubtator_link.services.publication_passage_service import PublicationPassageService
from pubtator_link.services.publication_service import PublicationService
from pubtator_link.services.review_context_service import ReviewContextService
from pubtator_link.services.review_preparation_queue import ReviewPreparationQueue


async def search_biomedical_entities_impl(
    request: SearchBiomedicalEntitiesRequest,
    *,
    client: PubTator3Client,
) -> dict[str, Any]:
    raw_response = await client.autocomplete_entity(
        query=request.query.strip(),
        concept=request.concept,
        limit=request.limit,
    )
    raw_results = cast(list[dict[str, Any]], raw_response)
    matches = [
        EntityMatch(
            identifier=item.get("_id", ""),
            name=item.get("name", ""),
            type=item.get("biotype", request.concept or "Unknown"),
            score=item.get("score"),
            synonyms=item.get("synonyms", []),
            db_id=item.get("db_id"),
            db=item.get("db"),
            match=item.get("match"),
        )
        for item in raw_results
    ]
    return EntityAutocompleteResponse(
        success=True,
        query=request.query.strip(),
        matches=matches,
        total_matches=len(matches),
        concept_filter=request.concept,
    ).model_dump()


async def fetch_publication_annotations_impl(
    request: FetchPublicationAnnotationsRequest,
    *,
    service: PublicationService,
) -> dict[str, Any]:
    result = await service.export_publications_list(
        pmids=request.pmids,
        format=request.format,
        full=request.full,
    )
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return dict(result)


async def get_publication_passages_impl(
    request: GetPublicationPassagesMcpRequest,
    *,
    service: PublicationPassageService,
) -> dict[str, Any]:
    response = await service.get_passages(
        PublicationPassageRequest(
            pmids=request.pmids,
            sections=request.sections,
            mode=request.mode,
            full=request.full,
            max_passages_per_pmid=request.max_passages_per_pmid,
            max_chars=request.max_chars,
            include_tables=request.include_tables,
            include_references=request.include_references,
        )
    )
    return response.model_dump()


async def estimate_publication_context_impl(
    request: EstimatePublicationContextMcpRequest,
    *,
    service: PublicationPassageService,
) -> dict[str, Any]:
    response = await service.estimate_context(
        PublicationContextEstimateRequest(
            pmids=request.pmids,
            sections=request.sections,
            mode=request.mode,
            full=request.full,
            max_passages_per_pmid=request.max_passages_per_pmid,
            include_tables=request.include_tables,
            include_references=request.include_references,
        )
    )
    return response.model_dump()


async def search_literature_impl(
    request: SearchLiteratureRequest,
    *,
    client: PubTator3Client,
) -> dict[str, Any]:
    result = await client.search_publications(
        text=request.text.strip(),
        page=request.page,
        sort=request.sort,
        filters=request.filters,
        sections=request.sections,
    )
    search_results = [
        SearchResult(
            pmid=item.get("pmid", ""),
            title=item.get("title", ""),
            abstract=item.get("abstract"),
            authors=item.get("authors", []),
            journal=item.get("journal"),
            pub_date=item.get("pub_date"),
            annotations=item.get("annotations", []),
            score=item.get("score"),
            pmcid=item.get("pmcid"),
            doi=item.get("doi"),
            date=item.get("date"),
            text_hl=item.get("text_hl"),
            citations=item.get("citations"),
        )
        for item in result.get("results", [])
    ]
    total_results = int(result.get("total", 0))
    per_page = int(result.get("per_page", 20))
    total_pages = (total_results + per_page - 1) // per_page if per_page else 0
    return SearchResponse(
        success=True,
        query=request.text.strip(),
        results=search_results,
        total_results=total_results,
        page=request.page,
        per_page=per_page,
        total_pages=total_pages,
        sort_order=request.sort,
    ).model_dump()


async def fetch_pmc_annotations_impl(
    request: FetchPmcAnnotationsRequest,
    *,
    service: PublicationService,
) -> dict[str, Any]:
    result = await service.export_pmc_publications_list(
        pmcids=request.pmcids,
        format=request.format,
    )
    documents = [
        document.model_dump() if hasattr(document, "model_dump") else dict(document)
        for document in result.documents
    ]
    return PublicationExportResponse(
        format=result.format,
        pmcids=request.pmcids,
        full_text=True,
        export_data={"documents": documents},
        count=len(request.pmcids),
    ).model_dump()


async def find_entity_relations_impl(
    request: FindEntityRelationsRequest,
    *,
    client: PubTator3Client,
) -> dict[str, Any]:
    raw_response = await client.find_relations(
        e1=request.entity_id,
        relation_type=request.relation_type,
        e2=request.target_entity_type,
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
        primary_entity=request.entity_id,
        related_entities=related_entities,
        total_relations=len(related_entities),
        relation_filter=request.relation_type,
        entity_filter=request.target_entity_type,
    ).model_dump()


async def submit_text_annotation_impl(
    request: SubmitTextAnnotationRequest,
    *,
    client: PubTator3Client,
) -> dict[str, Any]:
    if request.bioconcepts.lower() == "all":
        bioconcepts = list(text_processing_config.supported_bioconcepts)
    else:
        bioconcepts = [item.strip() for item in request.bioconcepts.split(",") if item.strip()]

    invalid_bioconcepts = [
        bioconcept
        for bioconcept in bioconcepts
        if bioconcept not in text_processing_config.supported_bioconcepts
    ]
    if invalid_bioconcepts:
        raise ValueError(
            f"Invalid bioconcept(s): {', '.join(invalid_bioconcepts)}. "
            f"Supported types: {', '.join(text_processing_config.supported_bioconcepts)}"
        )

    text = request.text.strip()
    session_id = await client.submit_text_annotation(text=text, bioconcept=bioconcepts[0])
    if len(text) < 1000:
        estimated_time = 15
    elif len(text) < 5000:
        estimated_time = 45
    else:
        estimated_time = 90

    return TextAnnotationSubmitResponse(
        success=True,
        session_id=session_id,
        status="submitted",
        bioconcepts=bioconcepts,
        estimated_time=estimated_time,
        message="Text submitted for processing. Use session_id to retrieve results.",
    ).model_dump()


async def get_text_annotation_results_impl(
    request: GetTextAnnotationResultsRequest,
    *,
    client: PubTator3Client,
) -> dict[str, Any]:
    result = await client.retrieve_text_annotation(session_id=request.session_id)
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
        session_id=request.session_id,
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
    request: IndexReviewEvidenceMcpRequest,
    *,
    queue: ReviewPreparationQueue,
) -> dict[str, Any]:
    api_request = IndexReviewEvidenceRequest(
        pmids=request.pmids,
        curated_urls=request.curated_urls,
        prepare_mode=request.prepare_mode,  # type: ignore[arg-type]
    )
    queued = 0
    already_prepared = 0
    for pmid in api_request.pmids:
        if await queue.enqueue_pmid(request.review_id, pmid):
            queued += 1
        else:
            already_prepared += 1
    for url in api_request.curated_urls:
        if await queue.enqueue_curated_url(request.review_id, url):
            queued += 1
        else:
            already_prepared += 1
    status = await queue.repository.preparation_status(request.review_id)
    return {
        "success": True,
        "review_id": request.review_id,
        "queued": queued,
        "already_prepared": already_prepared,
        "preparation_status": status.model_dump(),
    }


async def inspect_review_index_impl(
    request: InspectReviewIndexMcpRequest,
    *,
    service: ReviewContextService,
) -> dict[str, Any]:
    response = await service.inspect_review_index(
        review_id=request.review_id,
        request=InspectReviewIndexRequest(
            pmids=request.pmids,
            include_passage_samples=request.include_passage_samples,
            sample_per_pmid=request.sample_per_pmid,
        ),
    )
    return response.model_dump()


async def retrieve_review_context_impl(
    request: RetrieveReviewContextMcpRequest,
    *,
    service: ReviewContextService,
) -> dict[str, Any]:
    response = await service.retrieve_context(
        review_id=request.review_id,
        request=RetrieveReviewContextRequest(
            question=request.question,
            pmids=request.pmids,
            entity_ids=request.entity_ids,
            sections=request.sections,
            max_passages=request.max_passages,
            max_chars=request.max_chars,
            include_diagnostics=request.include_diagnostics,
        ),
    )
    return response.model_dump()


async def retrieve_review_context_batch_impl(
    request: RetrieveReviewContextBatchMcpRequest,
    *,
    service: ReviewContextService,
) -> dict[str, Any]:
    response = await service.retrieve_context_batch(
        review_id=request.review_id,
        request=RetrieveReviewContextBatchRequest(
            queries=request.queries,
            pmids=request.pmids,
            entity_ids=request.entity_ids,
            sections=request.sections,
            max_passages_per_query=request.max_passages_per_query,
            max_total_passages=request.max_total_passages,
            max_chars=request.max_chars,
            deduplicate_passages=request.deduplicate_passages,
            include_diagnostics=request.include_diagnostics,
        ),
    )
    return response.model_dump()
