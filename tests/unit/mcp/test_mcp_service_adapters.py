from __future__ import annotations

import json
from typing import ClassVar

import pytest

from pubtator_link.mcp.service_adapters import stage_research_session_impl


@pytest.mark.asyncio
async def test_search_entities_adapter_calls_client() -> None:
    from pubtator_link.mcp.service_adapters import search_biomedical_entities_impl

    class FakeClient:
        async def autocomplete_entity(
            self, query: str, concept: str | None, limit: int
        ) -> list[dict[str, object]]:
            return [{"_id": "@GENE_672", "name": "BRCA1", "biotype": "Gene", "score": 1.0}]

    result = await search_biomedical_entities_impl(
        client=FakeClient(),
        query="BRCA1",
        concept="Gene",
    )

    assert result["success"] is True
    assert result["matches"][0]["identifier"] == "@GENE_672"


@pytest.mark.asyncio
async def test_publication_adapter_validates_pmids() -> None:
    from pubtator_link.mcp.service_adapters import fetch_publication_annotations_impl

    class FakeService:
        async def export_publications_list(
            self, pmids: list[str], format: str, full: bool
        ) -> dict[str, object]:
            return {"pmids": pmids, "format": format, "full_text": full, "count": len(pmids)}

    result = await fetch_publication_annotations_impl(
        service=FakeService(),
        pmids=["29355051"],
        format="biocjson",
    )

    assert result["pmids"] == ["29355051"]
    assert result["format"] == "biocjson"


@pytest.mark.asyncio
async def test_publication_passages_adapter_calls_service() -> None:
    from pubtator_link.mcp.service_adapters import get_publication_passages_impl
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
        service=FakeService(),
        pmids=["29355051"],
    )

    assert result["success"] is True
    assert result["pmids"] == ["29355051"]
    assert "passages" in result


@pytest.mark.asyncio
async def test_preflight_review_sources_adapter_returns_hints() -> None:
    from pubtator_link.mcp.service_adapters import preflight_review_sources_impl
    from pubtator_link.models.review_rerag import SourceCoverageHint

    class FakeService:
        async def preflight_pmids(self, pmids: list[str]) -> list[SourceCoverageHint]:
            return [
                SourceCoverageHint(
                    pmid=pmids[0],
                    expected_coverage="abstract_only",
                    coverage_reason="no_pmcid",
                )
            ]

    result = await preflight_review_sources_impl(
        service=FakeService(),
        pmids=["40234174"],
    )

    assert result["success"] is True
    assert result["coverage_hints"][0]["pmid"] == "40234174"
    assert result["coverage_hints"][0]["coverage_reason"] == "no_pmcid"


@pytest.mark.asyncio
async def test_inspect_review_index_adapter_calls_service() -> None:
    from pubtator_link.mcp.service_adapters import inspect_review_index_impl
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
        service=FakeService(),
        review_id="rev_123",
    )

    assert result["success"] is True
    assert result["review_id"] == "rev_123"


@pytest.mark.asyncio
async def test_get_review_passages_by_id_adapter_calls_service() -> None:
    from pubtator_link.mcp.service_adapters import get_review_passages_by_id_impl
    from pubtator_link.models.review_rerag import ReviewPassageLookupResponse

    class FakeService:
        async def get_passages_by_id(
            self,
            review_id: str,
            passage_ids: list[str],
            max_chars_per_passage: int,
        ) -> ReviewPassageLookupResponse:
            return ReviewPassageLookupResponse(
                review_id=review_id,
                passages=[],
                not_found=passage_ids,
            )

    result = await get_review_passages_by_id_impl(
        service=FakeService(),
        review_id="rev_123",
        passage_ids=["p1"],
    )

    assert result["success"] is True
    assert result["not_found"] == ["p1"]


@pytest.mark.asyncio
async def test_get_neighboring_review_passages_adapter_calls_service() -> None:
    from pubtator_link.mcp.service_adapters import get_neighboring_review_passages_impl
    from pubtator_link.models.review_rerag import ReviewPassageLookupResponse

    class FakeService:
        async def get_neighboring_passages(
            self,
            review_id: str,
            passage_id: str,
            before: int,
            after: int,
            same_section: bool,
            max_chars_per_passage: int,
        ) -> ReviewPassageLookupResponse:
            return ReviewPassageLookupResponse(
                review_id=review_id,
                passages=[],
                not_found=[passage_id],
            )

    result = await get_neighboring_review_passages_impl(
        service=FakeService(),
        review_id="rev_123",
        passage_id="missing",
    )

    assert result["success"] is True
    assert result["not_found"] == ["missing"]


@pytest.mark.asyncio
async def test_export_review_audit_bundle_adapter_returns_bundle() -> None:
    from pubtator_link.mcp.service_adapters import export_review_audit_bundle_impl
    from pubtator_link.models.review_rerag import (
        PreparationStatus,
        ReviewAuditBundle,
        ReviewIndexTotals,
    )

    class FakeService:
        async def export_bundle(self, review_id: str) -> ReviewAuditBundle:
            return ReviewAuditBundle(
                review_id=review_id,
                generated_at="2026-05-01T10:00:00+00:00",
                preparation_status=PreparationStatus(complete=1),
                totals=ReviewIndexTotals(),
                sources=[],
                failed_sources=[],
                coverage_distribution={},
                resolver_attempts=[],
                passage_ids=[],
                stable_citation_keys={},
            )

    result = await export_review_audit_bundle_impl(
        service=FakeService(),
        review_id="rev_123",
    )

    assert set(result) == {"success", "audit_bundle"}
    assert result["success"] is True
    assert result["audit_bundle"]["review_id"] == "rev_123"


async def test_stage_research_session_impl_calls_service() -> None:
    class Service:
        async def stage(self, *, review_id, request):
            assert review_id == "review-1"
            assert request.query == "FMF"
            return type("Response", (), {"model_dump": lambda self: {"success": True}})()

    result = await stage_research_session_impl(
        service=Service(),
        review_id="review-1",
        query="FMF",
        pmids=None,
        max_candidates=10,
        stage_full_text=True,
    )

    assert result == {"success": True}


@pytest.mark.asyncio
async def test_index_review_evidence_adapter_returns_lifecycle_guidance() -> None:
    from pubtator_link.mcp.service_adapters import index_review_evidence_impl
    from pubtator_link.models.review_rerag import PreparationStatus

    class FakeRepository:
        async def preparation_status(self, review_id):
            return PreparationStatus(queued=1, complete=2)

    class FakeQueue:
        repository = FakeRepository()

        async def enqueue_pmid(self, review_id, pmid):
            return pmid == "40234174"

        async def enqueue_curated_url(self, review_id, url):
            return False

    result = await index_review_evidence_impl(
        queue=FakeQueue(),
        review_id="rev",
        pmids=["40234174", "40234175"],
        curated_urls=["https://example.org/already-prepared.pdf"],
    )

    assert result["queued"] == 1
    assert result["already_prepared"] == 2
    assert set(result) >= {"success", "review_id", "preparation_status"}
    assert result["retry_after_ms"] == 5000
    assert "already_prepared" in result["lifecycle_note"]
    assert "inspect_review_index" in result["lifecycle_note"]


@pytest.mark.asyncio
async def test_retrieve_review_context_batch_adapter_calls_service() -> None:
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl
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
        service=FakeService(),
        review_id="rev_123",
        queries=["colchicine children"],
    )

    assert result["success"] is True
    assert result["review_id"] == "rev_123"
    assert set(result) >= {"success", "review_id", "merged_context_pack"}
    assert result["merged_context_pack"]["question"] == "colchicine children"


@pytest.mark.asyncio
async def test_retrieve_review_context_batch_adapter_builds_request_from_flat_args() -> None:
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl
    from pubtator_link.models.review_rerag import (
        ContextPack,
        PreparationStatus,
        RetrieveReviewContextBatchResponse,
    )

    class RecordingService:
        review_id = None
        request = None

        async def retrieve_context_batch(self, review_id, request):
            self.review_id = review_id
            self.request = request
            return RetrieveReviewContextBatchResponse(
                review_id=review_id,
                response_mode=request.response_mode,
                results=[],
                merged_context_pack=ContextPack(question="", passages=[], citation_map={}),
                preparation_status=PreparationStatus(),
            )

    service = RecordingService()

    result = await retrieve_review_context_batch_impl(
        service=service,
        review_id="rev",
        queries=["MEFV", "colchicine"],
        response_mode="diagnostics",
        max_chars=8000,
        max_response_chars=12000,
        include_tables=False,
    )

    assert service.review_id == "rev"
    assert service.request.response_mode == "diagnostics"
    assert service.request.max_response_chars == 12000
    assert service.request.include_tables is False
    assert result["response_mode"] == "diagnostics"


@pytest.mark.asyncio
async def test_retrieve_review_context_batch_adapter_sets_budget_strategy() -> None:
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl
    from pubtator_link.models.review_rerag import (
        ContextPack,
        PreparationStatus,
        RetrieveReviewContextBatchResponse,
    )

    class RecordingService:
        request = None

        async def retrieve_context_batch(self, review_id, request):
            self.request = request
            return RetrieveReviewContextBatchResponse(
                review_id=review_id,
                response_mode=request.response_mode,
                results=[],
                merged_context_pack=ContextPack(question="", passages=[], citation_map={}),
                preparation_status=PreparationStatus(),
            )

    service = RecordingService()

    await retrieve_review_context_batch_impl(
        service=service,
        review_id="rev",
        queries=["guideline"],
        budget_strategy="scarcity_first",
        min_passages_per_source=2,
    )

    assert service.request.budget_strategy == "scarcity_first"
    assert service.request.min_passages_per_source == 2


@pytest.mark.asyncio
async def test_list_review_indexes_adapter_calls_lifecycle_service() -> None:
    from pubtator_link.mcp.service_adapters import list_review_indexes_impl
    from pubtator_link.models.review_rerag import ListReviewIndexesResponse

    class FakeService:
        async def list_indexes(self, *, limit: int, offset: int) -> ListReviewIndexesResponse:
            return ListReviewIndexesResponse(indexes=[])

    result = await list_review_indexes_impl(service=FakeService(), limit=10, offset=5)

    assert result == {"success": True, "indexes": []}


@pytest.mark.asyncio
async def test_get_review_index_summary_adapter_calls_lifecycle_service() -> None:
    from pubtator_link.mcp.service_adapters import get_review_index_summary_impl
    from pubtator_link.models.review_rerag import ReviewIndexSummaryResponse

    class FakeService:
        async def get_summary(self, review_id: str) -> ReviewIndexSummaryResponse:
            return ReviewIndexSummaryResponse(index=None)

    result = await get_review_index_summary_impl(service=FakeService(), review_id="review-1")

    assert result == {"success": True, "index": None}


@pytest.mark.asyncio
async def test_retrieve_review_context_adapter_builds_request_from_flat_args() -> None:
    from pubtator_link.mcp.service_adapters import retrieve_review_context_impl
    from pubtator_link.models.review_rerag import (
        ContextPack,
        PreparationStatus,
        RetrieveReviewContextResponse,
    )

    class RecordingService:
        review_id = None
        request = None

        async def retrieve_context(self, review_id, request):
            self.review_id = review_id
            self.request = request
            return RetrieveReviewContextResponse(
                review_id=review_id,
                context_pack=ContextPack(
                    question=request.question,
                    passages=[],
                    citation_map={},
                ),
                preparation_status=PreparationStatus(),
            )

    service = RecordingService()

    result = await retrieve_review_context_impl(
        service=service,
        review_id="rev",
        question="MEFV colchicine",
        pmids=["40234174"],
        include_tables=True,
    )

    assert service.review_id == "rev"
    assert service.request.pmids == ["40234174"]
    assert service.request.include_tables is True
    assert result["context_pack"]["question"] == "MEFV colchicine"


@pytest.mark.asyncio
async def test_inspect_review_index_adapter_builds_request_from_flat_args() -> None:
    from pubtator_link.mcp.service_adapters import inspect_review_index_impl
    from pubtator_link.models.review_rerag import (
        InspectReviewIndexResponse,
        PreparationStatus,
        ReviewIndexTotals,
    )

    class RecordingService:
        review_id = None
        request = None

        async def inspect_review_index(self, review_id, request):
            self.review_id = review_id
            self.request = request
            return InspectReviewIndexResponse(
                review_id=review_id,
                preparation_status=PreparationStatus(complete=1),
                sources=[],
                totals=ReviewIndexTotals(),
                failed_sources=[],
            )

    service = RecordingService()

    result = await inspect_review_index_impl(
        service=service,
        review_id="rev",
        pmids=["40234174"],
        include_passage_samples=True,
        sample_per_pmid=3,
    )

    assert service.review_id == "rev"
    assert service.request.pmids == ["40234174"]
    assert service.request.sample_per_pmid == 3
    assert result["review_id"] == "rev"


@pytest.mark.asyncio
async def test_search_literature_adapter_maps_client_results() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

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
        client=FakeClient(),
        text="BRCA1",
        sort="score desc",
        sections=["title"],
    )

    assert result["success"] is True
    assert result["query"] == "BRCA1"
    assert result["results"][0]["pmid"] == "29355051"


@pytest.mark.asyncio
async def test_search_literature_adapter_maps_flat_sections() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

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
                "results": [{"pmid": "29355051", "title": "BRCA1 mutations"}],
                "total": 1,
                "per_page": 20,
                "sections": sections,
            }

    result = await search_literature_impl(
        client=FakeClient(),
        text=" BRCA1 ",
        sort="score desc",
        sections=["title", "abstract"],
    )

    assert result["success"] is True
    assert result["query"] == "BRCA1"
    assert result["results"][0]["pmid"] == "29355051"


@pytest.mark.asyncio
async def test_search_literature_adapter_maps_pubtator3_count_and_metadata() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

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
                "results": [
                    {
                        "pmid": 39596913,
                        "title": "Guideline title",
                        "journal": "Ann Rheum Dis",
                        "authors": ["Smith J"],
                        "date": "2024",
                        "doi": "10.1000/test",
                        "pmcid": "PMC123",
                        "meta_date_publication": "2024 Oct 22",
                        "meta_volume": "83",
                        "meta_issue": "11",
                        "meta_pages": "123-130",
                        "publication_types": ["Guideline", "Practice Guideline"],
                        "citations": {"nlm": "Ann Rheum Dis. PMID: 39596913"},
                        "score": 12.5,
                    }
                ],
                "count": 2776,
                "total_pages": 278,
                "page_size": 10,
            }

    result = await search_literature_impl(client=FakeClient(), text="guideline")

    item = result["results"][0]
    assert result["total_results"] == 2776
    assert result["total_pages"] == 278
    assert result["per_page"] == 10
    assert item["pmid"] == "39596913"
    assert item["date"] == "2024"
    assert item["pub_date"] == "2024 Oct 22"
    assert item["doi"] == "10.1000/test"
    assert item["pmcid"] == "PMC123"
    assert item["volume"] == "83"
    assert item["issue"] == "11"
    assert item["pages"] == "123-130"
    assert item["publication_types"] == ["Guideline", "Practice Guideline"]
    assert item["citations"]["nlm"].endswith("39596913")


@pytest.mark.asyncio
async def test_search_literature_adapter_merges_flat_filters() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    class RecordingClient:
        filters = None

        async def search_publications(
            self,
            text: str,
            page: int,
            sort: str | None,
            filters: str | None,
            sections: str | None,
        ) -> dict[str, object]:
            self.filters = filters
            return {"results": [], "count": 0, "total_pages": 0, "page_size": 10}

    client = RecordingClient()

    await search_literature_impl(
        client=client,
        text="guideline",
        filters='{"journal":["Ann Rheum Dis"]}',
        publication_types=["Guideline", "Practice Guideline"],
        year_min=2020,
        year_max=2026,
    )

    assert json.loads(client.filters) == {
        "journal": ["Ann Rheum Dis"],
        "type": ["Guideline", "Practice Guideline"],
        "year": {"min": 2020, "max": 2026},
    }


@pytest.mark.asyncio
async def test_search_literature_adapter_rejects_filter_conflict() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    class RecordingClient:
        called = False

        async def search_publications(
            self,
            text: str,
            page: int,
            sort: str | None,
            filters: str | None,
            sections: str | None,
        ) -> dict[str, object]:
            self.called = True
            return {"results": [], "count": 0}

    client = RecordingClient()

    with pytest.raises(ValueError, match="type"):
        await search_literature_impl(
            client=client,
            text="guideline",
            filters='{"type":["Review"]}',
            publication_types=["Guideline"],
        )

    assert client.called is False


@pytest.mark.asyncio
async def test_search_literature_adapter_rejects_year_min_below_bounds() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    class RecordingClient:
        called = False

        async def search_publications(
            self,
            text: str,
            page: int,
            sort: str | None,
            filters: str | None,
            sections: str | None,
        ) -> dict[str, object]:
            self.called = True
            return {"results": [], "count": 0}

    client = RecordingClient()

    with pytest.raises(ValueError, match="year_min"):
        await search_literature_impl(
            client=client,
            text="guideline",
            year_min=1700,
        )

    assert client.called is False


@pytest.mark.asyncio
async def test_search_literature_adapter_rejects_year_max_above_bounds() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    class RecordingClient:
        called = False

        async def search_publications(
            self,
            text: str,
            page: int,
            sort: str | None,
            filters: str | None,
            sections: str | None,
        ) -> dict[str, object]:
            self.called = True
            return {"results": [], "count": 0}

    client = RecordingClient()

    with pytest.raises(ValueError, match="year_max"):
        await search_literature_impl(
            client=client,
            text="guideline",
            year_max=9999,
        )

    assert client.called is False


@pytest.mark.parametrize(
    ("filters", "match"),
    [
        ('{"year":{"min":1700}}', "year.min"),
        ('{"year":{"max":9999}}', "year.max"),
        ('{"year":{"min":2026,"max":2020}}', "year.max"),
    ],
)
@pytest.mark.asyncio
async def test_search_literature_adapter_rejects_raw_year_filter_validation(
    filters: str, match: str
) -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    class RecordingClient:
        called = False

        async def search_publications(
            self,
            text: str,
            page: int,
            sort: str | None,
            filters: str | None,
            sections: str | None,
        ) -> dict[str, object]:
            self.called = True
            return {"results": [], "count": 0}

    client = RecordingClient()

    with pytest.raises(ValueError, match=match):
        await search_literature_impl(
            client=client,
            text="guideline",
            filters=filters,
        )

    assert client.called is False


@pytest.mark.asyncio
async def test_search_biomedical_entities_adapter_accepts_flat_args() -> None:
    from pubtator_link.mcp.service_adapters import search_biomedical_entities_impl

    class FakeClient:
        async def autocomplete_entity(
            self, query: str, concept: str | None, limit: int
        ) -> list[dict[str, object]]:
            return [{"_id": "@GENE_672", "name": "BRCA1", "biotype": "Gene"}]

    result = await search_biomedical_entities_impl(
        client=FakeClient(),
        query="BRCA1",
        concept="Gene",
        limit=5,
    )

    assert result["success"] is True
    assert result["matches"][0]["identifier"] == "@GENE_672"


@pytest.mark.asyncio
async def test_publication_passages_adapter_builds_request_from_flat_args() -> None:
    from pubtator_link.mcp.service_adapters import get_publication_passages_impl
    from pubtator_link.models.publication_passages import (
        PublicationContextEstimate,
        PublicationPassageResponse,
    )

    class RecordingService:
        request = None

        async def get_passages(self, request):
            self.request = request
            return PublicationPassageResponse(
                pmids=request.pmids,
                mode=request.mode,
                passages=[],
                dropped=[],
                context_estimate=PublicationContextEstimate(
                    estimated_passages=0,
                    estimated_chars=0,
                    sections_by_pmid={"29355051": request.sections},
                    recommended_mode="compact_passages",
                    warning=None,
                ),
            )

    service = RecordingService()

    result = await get_publication_passages_impl(
        service=service,
        pmids=["29355051"],
        sections=["abstract"],
        include_references=True,
    )

    assert service.request.sections == ["abstract"]
    assert service.request.include_references is True
    assert result["pmids"] == ["29355051"]


@pytest.mark.asyncio
async def test_pmc_adapter_returns_publication_export_shape() -> None:
    from pubtator_link.mcp.service_adapters import fetch_pmc_annotations_impl

    class Document:
        def model_dump(self) -> dict[str, object]:
            return {"id": "PMC7696669"}

    class Result:
        format = "biocjson"
        documents: ClassVar[list[Document]] = [Document()]

    class FakeService:
        async def export_pmc_publications_list(self, pmcids: list[str], format: str) -> Result:
            return Result()

    result = await fetch_pmc_annotations_impl(service=FakeService(), pmcids=["PMC7696669"])

    assert result["pmcids"] == ["PMC7696669"]
    assert result["full_text"] is True
    assert result["export_data"]["documents"] == [{"id": "PMC7696669"}]


@pytest.mark.asyncio
async def test_relations_adapter_maps_related_entities() -> None:
    from pubtator_link.mcp.service_adapters import find_entity_relations_impl

    class FakeClient:
        async def find_relations(
            self, e1: str, relation_type: str | None, e2: str | None
        ) -> list[dict[str, object]]:
            return [{"target": "@DISEASE_COVID-19", "type": "treat", "pmids": ["32511357"]}]

    result = await find_entity_relations_impl(
        client=FakeClient(),
        entity_id="@CHEMICAL_remdesivir",
        relation_type="treat",
        target_entity_type="Disease",
    )

    assert result["success"] is True
    assert result["primary_entity"] == "@CHEMICAL_remdesivir"
    assert result["related_entities"][0]["entity_id"] == "@DISEASE_COVID-19"


@pytest.mark.asyncio
async def test_submit_text_annotation_adapter_returns_session_metadata() -> None:
    from pubtator_link.mcp.service_adapters import submit_text_annotation_impl

    class FakeClient:
        async def submit_text_annotation(self, text: str, bioconcept: str) -> str:
            return "ABC123DEF456"

    result = await submit_text_annotation_impl(
        client=FakeClient(),
        text="BRCA1 mutations",
        bioconcepts="Gene",
    )

    assert result["success"] is True
    assert result["session_id"] == "ABC123DEF456"
    assert result["bioconcepts"] == ["Gene"]


@pytest.mark.asyncio
async def test_get_text_annotation_results_adapter_maps_completed_results() -> None:
    from pubtator_link.mcp.service_adapters import get_text_annotation_results_impl

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

    result = await get_text_annotation_results_impl(client=FakeClient(), session_id="ABC123DEF456")

    assert result["success"] is True
    assert result["status"] == "completed"
    assert result["annotations"][0]["entity_id"] == "@GENE_672"
