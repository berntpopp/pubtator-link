from __future__ import annotations

from typing import Any, Literal, cast

from pubtator_link.api.client import PubTator3Client
from pubtator_link.config import text_processing_config
from pubtator_link.mcp.tools import (
    EstimatePublicationContextMcpRequest,
    FetchPmcAnnotationsRequest,
    FetchPublicationAnnotationsRequest,
    FindEntityRelationsRequest,
    GetTextAnnotationResultsRequest,
    IndexReviewEvidenceMcpRequest,
    SubmitTextAnnotationRequest,
)
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
    ReviewBatchResponseMode,
    ReviewTableMode,
)
from pubtator_link.services.publication_passage_service import PublicationPassageService
from pubtator_link.services.publication_service import PublicationService
from pubtator_link.services.review_context_service import ReviewContextService
from pubtator_link.services.review_preparation_queue import ReviewPreparationQueue


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
    *,
    client: PubTator3Client,
    text: str,
    page: int = 1,
    sort: str | None = None,
    filters: str | None = None,
    sections: list[str] | None = None,
) -> dict[str, Any]:
    normalized_text = text.strip()
    result = await client.search_publications(
        text=normalized_text,
        page=page,
        sort=sort,
        filters=filters,
        sections=",".join(sections) if sections else None,
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
        query=normalized_text,
        results=search_results,
        total_results=total_results,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        sort_order=sort,
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
        prepare_mode=request.prepare_mode,
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
            include_diagnostics=include_diagnostics,
            include_tables=include_tables,
            include_references=include_references,
            table_mode=table_mode,
            allow_truncated_passages=allow_truncated_passages,
            max_chars_per_passage=max_chars_per_passage,
        ),
    )
    return response.model_dump()
