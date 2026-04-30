from __future__ import annotations

from typing import ClassVar

import pytest


@pytest.mark.asyncio
async def test_search_entities_adapter_calls_client() -> None:
    from pubtator_link.mcp.service_adapters import search_biomedical_entities_impl
    from pubtator_link.mcp.tools import SearchBiomedicalEntitiesRequest

    class FakeClient:
        async def autocomplete_entity(
            self, query: str, concept: str | None, limit: int
        ) -> list[dict[str, object]]:
            return [{"_id": "@GENE_672", "name": "BRCA1", "biotype": "Gene", "score": 1.0}]

    result = await search_biomedical_entities_impl(
        SearchBiomedicalEntitiesRequest(query="BRCA1", concept="Gene"),
        client=FakeClient(),
    )

    assert result["success"] is True
    assert result["matches"][0]["identifier"] == "@GENE_672"


@pytest.mark.asyncio
async def test_publication_adapter_validates_pmids() -> None:
    from pubtator_link.mcp.service_adapters import fetch_publication_annotations_impl
    from pubtator_link.mcp.tools import FetchPublicationAnnotationsRequest

    class FakeService:
        async def export_publications_list(
            self, pmids: list[str], format: str, full: bool
        ) -> dict[str, object]:
            return {"pmids": pmids, "format": format, "full_text": full, "count": len(pmids)}

    result = await fetch_publication_annotations_impl(
        FetchPublicationAnnotationsRequest(pmids=["29355051"], format="biocjson"),
        service=FakeService(),
    )

    assert result["pmids"] == ["29355051"]
    assert result["format"] == "biocjson"


@pytest.mark.asyncio
async def test_publication_passages_adapter_calls_service() -> None:
    from pubtator_link.mcp.service_adapters import get_publication_passages_impl
    from pubtator_link.mcp.tools import GetPublicationPassagesMcpRequest
    from pubtator_link.models.publication_passages import (
        PublicationContextEstimate,
        PublicationPassageResponse,
    )

    class FakeService:
        async def get_passages(self, request):
            return PublicationPassageResponse(
                pmids=request.pmids,
                mode=request.mode,
                passages=[],
                dropped=[],
                context_estimate=PublicationContextEstimate(
                    estimated_passages=0,
                    estimated_chars=0,
                    sections_by_pmid={"29355051": []},
                    recommended_mode="compact_passages",
                    warning=None,
                ),
            )

    result = await get_publication_passages_impl(
        GetPublicationPassagesMcpRequest(pmids=["29355051"]),
        service=FakeService(),
    )

    assert result["success"] is True
    assert result["pmids"] == ["29355051"]
    assert "passages" in result


@pytest.mark.asyncio
async def test_inspect_review_index_adapter_calls_service() -> None:
    from pubtator_link.mcp.service_adapters import inspect_review_index_impl
    from pubtator_link.mcp.tools import InspectReviewIndexMcpRequest
    from pubtator_link.models.review_rerag import (
        InspectReviewIndexResponse,
        PreparationStatus,
        ReviewIndexTotals,
    )

    class FakeService:
        async def inspect_review_index(self, review_id, request):
            return InspectReviewIndexResponse(
                review_id=review_id,
                preparation_status=PreparationStatus(complete=1),
                sources=[],
                totals=ReviewIndexTotals(),
                failed_sources=[],
            )

    result = await inspect_review_index_impl(
        InspectReviewIndexMcpRequest(review_id="rev_123"),
        service=FakeService(),
    )

    assert result["success"] is True
    assert result["review_id"] == "rev_123"


@pytest.mark.asyncio
async def test_retrieve_review_context_batch_adapter_calls_service() -> None:
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl
    from pubtator_link.mcp.tools import RetrieveReviewContextBatchMcpRequest
    from pubtator_link.models.review_rerag import (
        ContextPack,
        PreparationStatus,
        RetrieveReviewContextBatchResponse,
    )

    class FakeService:
        async def retrieve_context_batch(self, review_id, request):
            return RetrieveReviewContextBatchResponse(
                review_id=review_id,
                results=[],
                merged_context_pack=ContextPack(
                    question="\n".join(request.queries),
                    passages=[],
                    citation_map={},
                ),
                preparation_status=PreparationStatus(complete=1),
            )

    result = await retrieve_review_context_batch_impl(
        RetrieveReviewContextBatchMcpRequest(
            review_id="rev_123",
            queries=["colchicine children"],
        ),
        service=FakeService(),
    )

    assert result["success"] is True
    assert result["review_id"] == "rev_123"
    assert result["merged_context_pack"]["question"] == "colchicine children"


@pytest.mark.asyncio
async def test_search_literature_adapter_maps_client_results() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl
    from pubtator_link.mcp.tools import SearchLiteratureRequest

    class FakeClient:
        async def search_publications(
            self,
            text: str,
            page: int,
            sort: str | None,
            filters: str | None,
            sections: str | None,
        ) -> dict[str, object]:
            return {
                "results": [{"pmid": 29355051, "title": "BRCA1 mutations"}],
                "total": 1,
                "per_page": 20,
            }

    result = await search_literature_impl(
        SearchLiteratureRequest(text="BRCA1", sort="score desc", sections="title"),
        client=FakeClient(),
    )

    assert result["success"] is True
    assert result["query"] == "BRCA1"
    assert result["results"][0]["pmid"] == "29355051"


@pytest.mark.asyncio
async def test_pmc_adapter_returns_publication_export_shape() -> None:
    from pubtator_link.mcp.service_adapters import fetch_pmc_annotations_impl
    from pubtator_link.mcp.tools import FetchPmcAnnotationsRequest

    class Document:
        def model_dump(self) -> dict[str, object]:
            return {"id": "PMC7696669"}

    class Result:
        format = "biocjson"
        documents: ClassVar[list[Document]] = [Document()]

    class FakeService:
        async def export_pmc_publications_list(self, pmcids: list[str], format: str) -> Result:
            return Result()

    result = await fetch_pmc_annotations_impl(
        FetchPmcAnnotationsRequest(pmcids=["PMC7696669"], format="biocjson"),
        service=FakeService(),
    )

    assert result["pmcids"] == ["PMC7696669"]
    assert result["full_text"] is True
    assert result["export_data"]["documents"] == [{"id": "PMC7696669"}]


@pytest.mark.asyncio
async def test_relations_adapter_maps_related_entities() -> None:
    from pubtator_link.mcp.service_adapters import find_entity_relations_impl
    from pubtator_link.mcp.tools import FindEntityRelationsRequest

    class FakeClient:
        async def find_relations(
            self, e1: str, relation_type: str | None, e2: str | None
        ) -> list[dict[str, object]]:
            return [{"target": "@DISEASE_COVID-19", "type": "treat", "pmids": ["32511357"]}]

    result = await find_entity_relations_impl(
        FindEntityRelationsRequest(
            entity_id="@CHEMICAL_remdesivir",
            relation_type="treat",
            target_entity_type="Disease",
        ),
        client=FakeClient(),
    )

    assert result["success"] is True
    assert result["primary_entity"] == "@CHEMICAL_remdesivir"
    assert result["related_entities"][0]["entity_id"] == "@DISEASE_COVID-19"


@pytest.mark.asyncio
async def test_submit_text_annotation_adapter_returns_session_metadata() -> None:
    from pubtator_link.mcp.service_adapters import submit_text_annotation_impl
    from pubtator_link.mcp.tools import SubmitTextAnnotationRequest

    class FakeClient:
        async def submit_text_annotation(self, text: str, bioconcept: str) -> str:
            return "ABC123DEF456"

    result = await submit_text_annotation_impl(
        SubmitTextAnnotationRequest(text="BRCA1 mutations", bioconcepts="Gene"),
        client=FakeClient(),
    )

    assert result["success"] is True
    assert result["session_id"] == "ABC123DEF456"
    assert result["bioconcepts"] == ["Gene"]


@pytest.mark.asyncio
async def test_get_text_annotation_results_adapter_maps_completed_results() -> None:
    from pubtator_link.mcp.service_adapters import get_text_annotation_results_impl
    from pubtator_link.mcp.tools import GetTextAnnotationResultsRequest

    class FakeClient:
        async def retrieve_text_annotation(self, session_id: str) -> dict[str, object]:
            return {
                "status": "completed",
                "original_text": "BRCA1 mutations",
                "bioconcept": "Gene",
                "annotations": [
                    {
                        "start": 0,
                        "end": 5,
                        "text": "BRCA1",
                        "entity_id": "@GENE_672",
                        "entity_type": "Gene",
                    }
                ],
            }

    result = await get_text_annotation_results_impl(
        GetTextAnnotationResultsRequest(session_id="ABC123DEF456"),
        client=FakeClient(),
    )

    assert result["success"] is True
    assert result["status"] == "completed"
    assert result["annotations"][0]["entity_id"] == "@GENE_672"
