from __future__ import annotations

import json
from typing import ClassVar

import pytest

from pubtator_link.mcp.service_adapters import stage_research_session_impl
from pubtator_link.models.review_rerag import (
    PreparationStatus,
    ReviewAuditBundle,
    ReviewIndexTotals,
)


class _FakeReviewAuditBundleService:
    async def export_bundle(
        self, review_id: str, *, session_id: str | None = None
    ) -> ReviewAuditBundle:
        return ReviewAuditBundle(
            review_id=review_id,
            session_id=session_id,
            generated_at="2026-05-02T00:00:00Z",
            preparation_status=PreparationStatus(),
            totals=ReviewIndexTotals(),
            sources=[],
            failed_sources=[],
            coverage_distribution={},
            resolver_attempts=[],
            passage_ids=[],
            stable_citation_keys={},
            index_snapshot_date="2026-05-02",
        )


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
async def test_search_biomedical_entities_accepts_phenotype() -> None:
    from pubtator_link.mcp.service_adapters import search_biomedical_entities_impl

    class FakeClient:
        async def autocomplete_entity(
            self, query: str, concept: str | None, limit: int
        ) -> list[dict[str, object]]:
            return [
                {
                    "_id": "@PHENOTYPE_HP:0001945",
                    "name": "Fever",
                    "biotype": "Phenotype",
                }
            ]

    result = await search_biomedical_entities_impl(
        client=FakeClient(),
        query="familial Mediterranean fever",
        concept="Phenotype",
    )

    assert result["concept_filter"] == "Phenotype"


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
async def test_get_publication_metadata_impl_returns_typed_payload() -> None:
    from pubtator_link.mcp import service_adapters
    from pubtator_link.models.publication_metadata import PublicationMetadataResponse

    class FakeService:
        async def get_metadata(self, request):
            assert request.pmids == ["33454820"]
            return PublicationMetadataResponse(
                success=True,
                metadata=[],
                failed_pmids={},
                _meta={"next_commands": []},
            )

    result = await service_adapters.get_publication_metadata_impl(
        service=FakeService(),
        pmids=["33454820"],
        include_mesh=True,
        include_publication_types=True,
        include_citations="both",
        include_coverage=True,
    )

    assert result["success"] is True
    assert result["metadata"] == []


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
                index_snapshot_date="2026-05-02",
            )

    result = await inspect_review_index_impl(
        service=FakeService(),
        review_id="rev_123",
    )

    assert result["success"] is True
    assert result["review_id"] == "rev_123"
    assert result["index_snapshot_date"] is not None


@pytest.mark.asyncio
async def test_get_review_passages_by_id_adapter_calls_service() -> None:
    from pubtator_link.mcp.service_adapters import get_review_passages_by_id_impl
    from pubtator_link.models.review_rerag import ReviewPassageLookupResponse

    class FakeService:
        async def get_passages_by_id(
            self,
            review_id: str,
            passage_ids: list[str],
            session_id: str | None,
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
async def test_get_review_audit_trail_adapter_calls_service() -> None:
    from pubtator_link.mcp.service_adapters import get_review_audit_trail_impl
    from pubtator_link.models.review_rerag import ReviewAuditTrailItem, ReviewAuditTrailResponse

    class Service:
        async def get_audit_trail(self, **kwargs):
            assert kwargs["review_id"] == "rev-1"
            assert kwargs["passage_ids"] == ["p1"]
            return ReviewAuditTrailResponse(
                review_id="rev-1",
                items=[
                    ReviewAuditTrailItem(
                        passage_id="p1",
                        stable_citation_key="c_1",
                        section="abstract",
                        quote="Evidence text.",
                        char_count=14,
                    )
                ],
                audit_block="- c_1 PMID unavailable p1 abstract: Evidence text.",
            )

    result = await get_review_audit_trail_impl(
        service=Service(),
        review_id="rev-1",
        passage_ids=["p1"],
    )

    assert result["success"] is True
    assert result["items"][0]["stable_citation_key"] == "c_1"


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
            session_id: str | None,
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

    class FakeService:
        async def export_bundle(
            self, review_id: str, *, session_id: str | None = None
        ) -> ReviewAuditBundle:
            return ReviewAuditBundle(
                review_id=review_id,
                session_id=session_id,
                generated_at="2026-05-01T10:00:00+00:00",
                preparation_status=PreparationStatus(complete=1),
                totals=ReviewIndexTotals(),
                sources=[],
                failed_sources=[],
                coverage_distribution={},
                resolver_attempts=[],
                passage_ids=[],
                stable_citation_keys={},
                index_snapshot_date="2026-05-02",
            )

    result = await export_review_audit_bundle_impl(
        service=FakeService(),
        review_id="rev_123",
    )

    assert set(result) == {"success", "audit_bundle"}
    assert result["success"] is True
    assert result["audit_bundle"]["review_id"] == "rev_123"
    assert result["audit_bundle"]["index_snapshot_date"] is not None


@pytest.mark.asyncio
async def test_export_review_audit_bundle_adapter_writes_new_file(tmp_path) -> None:
    from pubtator_link.mcp.service_adapters import export_review_audit_bundle_impl

    export_path = tmp_path / "audit.json"

    result = await export_review_audit_bundle_impl(
        service=_FakeReviewAuditBundleService(),
        review_id="rev_123",
        export_path=str(export_path),
    )

    assert result == {"success": True, "export_path": str(export_path)}
    written = json.loads(export_path.read_text(encoding="utf-8"))
    assert written["review_id"] == "rev_123"


@pytest.mark.asyncio
async def test_export_review_audit_bundle_adapter_refuses_existing_file(tmp_path) -> None:
    from pubtator_link.mcp.service_adapters import export_review_audit_bundle_impl

    export_path = tmp_path / "audit.json"
    export_path.write_text("do not replace", encoding="utf-8")

    result = await export_review_audit_bundle_impl(
        service=_FakeReviewAuditBundleService(),
        review_id="rev_123",
        export_path=str(export_path),
    )

    assert result["success"] is False
    assert result["error"]["field_errors"][0]["field"] == "export_path"
    assert "already exists" in result["error"]["field_errors"][0]["reason"]
    assert export_path.read_text(encoding="utf-8") == "do not replace"


@pytest.mark.asyncio
async def test_export_review_audit_bundle_adapter_refuses_directory(tmp_path) -> None:
    from pubtator_link.mcp.service_adapters import export_review_audit_bundle_impl

    result = await export_review_audit_bundle_impl(
        service=_FakeReviewAuditBundleService(),
        review_id="rev_123",
        export_path=str(tmp_path),
    )

    assert result["success"] is False
    assert result["error"]["field_errors"][0]["field"] == "export_path"
    assert "directory" in result["error"]["field_errors"][0]["reason"]


@pytest.mark.asyncio
async def test_export_review_audit_bundle_adapter_returns_field_error_without_inline(
    tmp_path,
) -> None:
    from pubtator_link.mcp.service_adapters import export_review_audit_bundle_impl

    result = await export_review_audit_bundle_impl(
        service=_FakeReviewAuditBundleService(),
        review_id="rev_123",
        export_path=str(tmp_path / "missing" / "audit.json"),
        fallback_inline=False,
    )

    assert result["success"] is False
    assert result["error"]["code"] == "validation_failed"
    assert result["error"]["field_errors"][0]["field"] == "export_path"


@pytest.mark.asyncio
async def test_export_review_audit_bundle_adapter_returns_inline_fallback() -> None:
    from pubtator_link.mcp.service_adapters import export_review_audit_bundle_impl
    from pubtator_link.models.review_rerag import (
        PreparationStatus,
        ReviewAuditBundle,
        ReviewIndexTotals,
    )

    class Service:
        async def export_bundle(self, review_id, session_id=None):
            return ReviewAuditBundle(
                review_id=review_id,
                session_id=session_id,
                generated_at="2026-05-02T00:00:00Z",
                preparation_status=PreparationStatus(),
                totals=ReviewIndexTotals(),
                sources=[],
                failed_sources=[],
                coverage_distribution={},
                resolver_attempts=[],
                passage_ids=[],
                stable_citation_keys={},
            )

    result = await export_review_audit_bundle_impl(
        service=Service(),
        review_id="r1",
        fallback_inline=True,
        export_path="/not/writable/audit.json",
    )

    assert result["success"] is True
    assert result["inline_bundle"] is not None
    assert result["export_path"] is None


@pytest.mark.asyncio
async def test_export_review_audit_bundle_oversized_inline_fallback_preserves_field_errors(
    monkeypatch, tmp_path
) -> None:
    from pubtator_link.mcp import service_adapters

    monkeypatch.setattr(service_adapters, "INLINE_AUDIT_BUNDLE_MAX_BYTES", 1)

    result = await service_adapters.export_review_audit_bundle_impl(
        service=_FakeReviewAuditBundleService(),
        review_id="rev_123",
        export_path=str(tmp_path / "missing" / "audit.json"),
        fallback_inline=True,
    )

    assert result["success"] is False
    assert result["error"]["code"] == "export_unavailable"
    assert result["error"]["field_errors"][0]["field"] == "export_path"


async def test_stage_research_session_impl_calls_service() -> None:
    class Service:
        async def stage(self, *, review_id, request):
            assert review_id == "review-1"
            assert request.query == "FMF"
            assert request.session_id == "session-1"
            assert request.pmids == ["40234174"]
            assert request.page == 2
            assert request.sort == "score desc"
            assert request.filters == "year:2024"
            assert request.publication_types == ["Guideline"]
            assert request.year_min == 2020
            assert request.year_max == 2026
            assert request.sections == ["title", "abstract"]
            assert request.max_candidates == 10
            assert request.stage_full_text is False
            return type("Response", (), {"model_dump": lambda self: {"success": True}})()

    result = await stage_research_session_impl(
        service=Service(),
        review_id="review-1",
        query="FMF",
        pmids=["40234174"],
        session_id="session-1",
        page=2,
        sort="score desc",
        filters="year:2024",
        publication_types=["Guideline"],
        year_min=2020,
        year_max=2026,
        sections=["title", "abstract"],
        max_candidates=10,
        stage_full_text=False,
    )

    assert result == {"success": True}


@pytest.mark.asyncio
async def test_suggest_corpus_impl_returns_candidate_pmids() -> None:
    from pubtator_link.mcp import service_adapters
    from pubtator_link.models.corpus_suggestion import CorpusSuggestionResponse

    class FakeService:
        async def suggest(self, request):
            assert request.question == "FMF MEFV VUS colchicine"
            return CorpusSuggestionResponse(
                candidate_pmids=["26802180"],
                candidates=[],
                searches=[],
                _meta={"next_commands": ["pubtator.index_review_evidence"]},
            )

    result = await service_adapters.suggest_corpus_impl(
        service=FakeService(),
        question="FMF MEFV VUS colchicine",
        max_pmids=8,
        entity_ids=[],
        must_include_pmids=[],
        prefer_guidelines=True,
        include_metadata=True,
    )

    assert result["candidate_pmids"] == ["26802180"]
    assert result["_meta"]["next_commands"] == ["pubtator.index_review_evidence"]


async def test_stage_research_session_impl_serializes_meta_alias() -> None:
    from pubtator_link.models.review_rerag import (
        ResearchSessionManifest,
        StageResearchSessionResponse,
    )

    class Service:
        async def stage(self, *, review_id, request):
            return StageResearchSessionResponse(
                manifest=ResearchSessionManifest(session_id="session-1", review_id=review_id),
                meta={"retry_after_ms": 5000},
            )

    result = await stage_research_session_impl(
        service=Service(),
        review_id="review-1",
        query="FMF",
    )

    assert result["_meta"] == {"retry_after_ms": 5000}
    assert "meta" not in result


@pytest.mark.asyncio
async def test_review_quickstart_adapter_returns_retrieval_handoff() -> None:
    from pubtator_link.mcp.service_adapters import review_quickstart_impl
    from pubtator_link.models.review_rerag import (
        InspectReviewIndexResponse,
        PreparationStatus,
        ResearchSessionManifest,
        ReviewIndexTotals,
        StageResearchSessionResponse,
    )

    class StageService:
        async def stage(self, *, review_id, request):
            assert review_id.startswith("quickstart-")
            assert request.query == "MEFV colchicine"
            assert request.max_candidates == 8
            return StageResearchSessionResponse(
                manifest=ResearchSessionManifest(
                    session_id="session-1",
                    review_id=review_id,
                    query=request.query,
                    coverage_summary={"abstract_only": 1},
                    preparation_status=PreparationStatus(complete=1),
                ),
                meta={"next_commands": ["pubtator.retrieve_review_context_batch"]},
            )

    class ContextService:
        async def inspect_review_index(self, review_id, request):
            assert request.session_id == "session-1"
            return InspectReviewIndexResponse(
                review_id=review_id,
                preparation_status=PreparationStatus(complete=1),
                sources=[],
                totals=ReviewIndexTotals(pmid_count=1, source_count=1, passage_count=3),
                failed_sources=[],
                coverage_summary={"abstract_only": 1},
            )

    result = await review_quickstart_impl(
        stage_service=StageService(),
        context_service=ContextService(),
        topic="MEFV colchicine",
        n_pmids=8,
    )

    assert result["ready_to_retrieve"] is True
    assert result["review_id"].startswith("quickstart-")
    assert result["session_id"] == "session-1"
    assert result["coverage_summary"] == {"abstract_only": 1}
    assert result["next_commands"][0] == "pubtator.retrieve_review_context_batch"


@pytest.mark.asyncio
async def test_ground_question_adapter_chains_search_index_inspect_retrieve() -> None:
    from pubtator_link.mcp import service_adapters
    from pubtator_link.models.review_rerag import (
        ContextPack,
        InspectReviewIndexResponse,
        PreparationStatus,
        RetrieveReviewContextBatchResponse,
        ReviewIndexTotals,
        ReviewSourceSummary,
    )

    class FakeClient:
        search_kwargs: ClassVar[dict[str, object] | None] = None

        async def search_publications(self, **kwargs):
            self.search_kwargs = kwargs
            return {
                "count": 4,
                "page": 1,
                "results": [
                    {"pmid": "11111111", "title": "First"},
                    {"pmid": "11111111", "title": "Duplicate"},
                    {"pmid": "22222222", "title": "Second"},
                    {"pmid": "33333333", "title": "Third"},
                ],
            }

    class FakeQueue:
        repository = object()

    indexing_services = []

    class FakeIndexingService:
        def __init__(self, **kwargs):
            self.init_kwargs = kwargs
            self.review_id = None
            self.request = None
            indexing_services.append(self)

        async def index_review_evidence(self, review_id, request):
            self.review_id = review_id
            self.request = request
            return {"success": True}

    class FakeContextService:
        inspect_review_id = None
        inspect_request = None
        retrieve_review_id = None
        retrieve_request = None

        async def inspect_review_index(self, review_id, request):
            self.inspect_review_id = review_id
            self.inspect_request = request
            return InspectReviewIndexResponse(
                review_id=review_id,
                preparation_status=PreparationStatus(complete=2),
                sources=[
                    ReviewSourceSummary(
                        source_id="PMID:11111111",
                        pmid="11111111",
                        source_kind="pubtator_abstract",
                        job_status="complete",
                        passage_count=1,
                        coverage="abstract_only",
                    )
                ],
                totals=ReviewIndexTotals(passage_count=2),
                failed_sources=[],
                coverage_summary={"full_text": 2},
            )

        async def retrieve_context_batch(self, review_id, request):
            self.retrieve_review_id = review_id
            self.retrieve_request = request
            return RetrieveReviewContextBatchResponse(
                review_id=review_id,
                response_mode=request.response_mode,
                results=[],
                merged_context_pack=ContextPack(
                    question=request.queries[0],
                    passages=[],
                    citation_map={},
                ),
                preparation_status=PreparationStatus(complete=2),
            )

    queue = FakeQueue()
    context_service = FakeContextService()
    result = await service_adapters.ground_question_impl(
        client=FakeClient(),
        queue=queue,
        context_service=context_service,
        question=" Does colchicine prevent FMF flares? ",
        max_pmids=3,
        entity_ids=["@CHEMICAL_colchicine"],
        wait_until_ready=True,
        review_indexing_service_factory=FakeIndexingService,
    )

    assert result["success"] is True
    assert result["question"] == "Does colchicine prevent FMF flares?"
    assert result["selected_pmids"] == ["11111111", "22222222"]
    assert len(result["selected_pmids"]) <= 3
    assert len(result["selected_pmids"]) == len(set(result["selected_pmids"]))
    assert result["search_total_results"] == 4
    assert result["ready_to_retrieve"] is True
    assert result["coverage_summary"] == {"full_text": 2}
    assert result["next_tools"] == [
        "pubtator.record_review_context",
        "pubtator.get_review_audit_trail",
    ]
    assert "_meta" not in result

    indexing_service = indexing_services[0]
    assert indexing_service.init_kwargs == {
        "repository": queue.repository,
        "queue": queue,
    }
    assert indexing_service.request.pmids == ["11111111", "22222222"]
    assert indexing_service.request.wait_for_completion is True
    assert indexing_service.request.wait_for_status == "complete_or_partial"
    assert context_service.inspect_request.pmids == ["11111111", "22222222"]
    assert context_service.retrieve_request.queries == ["Does colchicine prevent FMF flares?"]
    assert context_service.retrieve_request.pmids == ["11111111", "22222222"]
    assert context_service.retrieve_request.entity_ids == ["@CHEMICAL_colchicine"]
    assert context_service.retrieve_request.max_total_passages == 8
    assert context_service.retrieve_request.max_response_chars == 12000
    assert context_service.retrieve_request.response_mode == "compact"
    assert context_service.retrieve_request.include_diagnostics is False
    assert result["context"]["merged_context_pack"]["question"] == (
        "Does colchicine prevent FMF flares?"
    )


@pytest.mark.asyncio
async def test_ground_question_adapter_no_pmids_returns_search_recovery() -> None:
    from pubtator_link.mcp import service_adapters

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {"count": 0, "page": 1, "results": []}

    class FakeQueue:
        repository = object()

    class FakeContextService:
        async def inspect_review_index(self, review_id, request):
            raise AssertionError("inspect should not be called without selected PMIDs")

        async def retrieve_context_batch(self, review_id, request):
            raise AssertionError("retrieve should not be called without selected PMIDs")

    def fail_indexing_service_factory(**kwargs):
        raise AssertionError("index should not be called without selected PMIDs")

    result = await service_adapters.ground_question_impl(
        client=FakeClient(),
        queue=FakeQueue(),
        context_service=FakeContextService(),
        question="No matching biomedical literature",
        max_pmids=8,
        review_indexing_service_factory=fail_indexing_service_factory,
    )

    assert result["success"] is True
    assert result["selected_pmids"] == []
    assert result["ready_to_retrieve"] is False
    assert result["context"] is None
    assert result["next_tools"] == ["pubtator.search_literature"]
    assert result["recovery"] == [
        "Refine the search query or provide candidate PMIDs explicitly.",
    ]
    assert "_meta" not in result


@pytest.mark.asyncio
async def test_ground_question_adapter_waits_when_selected_pmids_are_not_ready() -> None:
    from pubtator_link.mcp import service_adapters
    from pubtator_link.models.review_rerag import (
        InspectReviewIndexResponse,
        PreparationStatus,
        ReviewIndexTotals,
    )

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "count": 1,
                "page": 1,
                "results": [{"pmid": "44444444", "title": "New selected source"}],
            }

    class FakeQueue:
        repository = object()

    class FakeIndexingService:
        def __init__(self, **kwargs):
            pass

        async def index_review_evidence(self, review_id, request):
            return {"success": True}

    class FakeContextService:
        async def inspect_review_index(self, review_id, request):
            return InspectReviewIndexResponse(
                review_id=review_id,
                preparation_status=PreparationStatus(complete=1),
                sources=[],
                totals=ReviewIndexTotals(passage_count=5),
                failed_sources=[],
                coverage_summary={},
            )

        async def retrieve_context_batch(self, review_id, request):
            raise AssertionError("retrieval should wait for selected PMIDs to be ready")

    result = await service_adapters.ground_question_impl(
        client=FakeClient(),
        queue=FakeQueue(),
        context_service=FakeContextService(),
        question="new source question",
        review_id="existing-review",
        review_indexing_service_factory=FakeIndexingService,
    )

    assert result["selected_pmids"] == ["44444444"]
    assert result["ready_to_retrieve"] is False
    assert result["context"] is None
    assert result["next_tools"] == [
        "pubtator.inspect_review_index",
        "pubtator.retrieve_review_context_batch",
    ]


@pytest.mark.asyncio
async def test_index_review_evidence_adapter_returns_lifecycle_guidance() -> None:
    from pubtator_link.mcp.service_adapters import index_review_evidence_impl
    from pubtator_link.models.review_rerag import PreparationStatus

    class FakeRepository:
        async def preparation_job_statuses(self, review_id, source_ids):
            return {
                "PMID:40234175": "complete",
                "URL:https://example.org/already-prepared.pdf": "complete",
            }

        async def source_coverage_summary(self, review_id, source_ids):
            return {
                "total_sources": 3,
                "full_text": 1,
                "abstract_only": 2,
                "title_only": 0,
                "failed": 0,
            }

        async def preparation_status(self, review_id, *, session_id=None):
            return PreparationStatus(queued=1, complete=2)

    class FakeQueue:
        repository = FakeRepository()

        async def enqueue_pmid(self, review_id, pmid):
            return "newly_queued" if pmid == "40234174" else "already_indexed"

        async def enqueue_curated_url(self, review_id, url):
            return "already_indexed"

    result = await index_review_evidence_impl(
        queue=FakeQueue(),
        review_id="rev",
        pmids=["40234174", "40234175"],
        curated_urls=["https://example.org/already-prepared.pdf"],
    )

    assert result["queued"] == 1
    assert result["already_prepared"] == 2
    assert set(result) >= {"success", "review_id", "preparation_status"}
    assert result["retry_after_ms"] == 3000
    assert result["index_snapshot_date"] is not None
    assert result["source_preflight_summary"]["abstract_only"] == 2
    assert "abstract_only" in result["source_preflight_message"]
    assert "already indexed sources are no-ops" in result["lifecycle_note"]
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
                index_snapshot_date="2026-05-02",
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
    assert result["index_snapshot_date"] is not None


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
                index_snapshot_date="2026-05-02",
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
        dry_run=True,
    )

    assert service.review_id == "rev"
    assert service.request.response_mode == "diagnostics"
    assert service.request.max_response_chars == 12000
    assert service.request.include_tables is False
    assert service.request.dry_run is True
    assert result["response_mode"] == "diagnostics"
    assert result["index_snapshot_date"] is not None


@pytest.mark.asyncio
async def test_retrieve_review_context_batch_adapter_auto_fits_omitted_budgets() -> None:
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl
    from pubtator_link.models.review_rerag import (
        ContextBudget,
        ContextPack,
        PreparationStatus,
        RetrieveReviewContextBatchResponse,
    )

    class RecordingService:
        request = None

        async def retrieve_context_batch(self, review_id, request):
            self.request = request
            budget_source = getattr(request, "budget_source", None)
            return RetrieveReviewContextBatchResponse(
                review_id=review_id,
                response_mode=request.response_mode,
                results=[],
                merged_context_pack=ContextPack(question="q", passages=[], citation_map={}),
                preparation_status=PreparationStatus(),
                budget=ContextBudget(
                    max_chars=request.max_chars,
                    text_chars=0,
                    estimated_json_chars=1200,
                    estimated_total_chars=1200,
                    estimated_tokens=334,
                    budget_source=budget_source,
                ),
                budget_source=budget_source,
            )

    service = RecordingService()

    result = await retrieve_review_context_batch_impl(
        service=service,
        review_id="rev",
        queries=["MEFV"],
        max_total_passages=14,
        max_chars_per_passage=2200,
    )

    assert service.request.max_chars == 30800
    assert service.request.max_response_chars == 61600
    assert getattr(service.request, "budget_source", None) == "auto_fit"
    assert result.get("budget_source") == "auto_fit"
    assert result["budget"]["budget_source"] == "auto_fit"


@pytest.mark.asyncio
async def test_retrieve_review_context_batch_adapter_preserves_explicit_budgets() -> None:
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
                merged_context_pack=ContextPack(question="q", passages=[], citation_map={}),
                preparation_status=PreparationStatus(),
                budget_source=getattr(request, "budget_source", None),
            )

    service = RecordingService()

    result = await retrieve_review_context_batch_impl(
        service=service,
        review_id="rev",
        queries=["MEFV"],
        max_chars=8000,
        max_response_chars=12000,
    )

    assert service.request.max_chars == 8000
    assert service.request.max_response_chars == 12000
    assert getattr(service.request, "budget_source", None) == "caller"
    assert result.get("budget_source") == "caller"


@pytest.mark.asyncio
async def test_retrieve_review_context_batch_adapter_derives_omitted_response_budget() -> None:
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
                merged_context_pack=ContextPack(question="q", passages=[], citation_map={}),
                preparation_status=PreparationStatus(),
                budget_source=getattr(request, "budget_source", None),
            )

    service = RecordingService()

    result = await retrieve_review_context_batch_impl(
        service=service,
        review_id="rev",
        queries=["MEFV"],
        max_chars=50_000,
    )

    assert service.request.max_chars == 50_000
    assert service.request.max_response_chars == 100_000
    assert getattr(service.request, "budget_source", None) == "caller"
    assert result.get("budget_source") == "caller"


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
async def test_retrieve_review_context_batch_adapter_omits_resolver_trace_by_default() -> None:
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl

    class ResponseWithTrace:
        def model_dump(self, **kwargs):
            return {
                "success": True,
                "review_id": "review-1",
                "resolver_attempts": [{"source_kind": "pubtator_full_bioc"}],
                "sources": [
                    {"source_id": "s1", "resolver_attempts": [{"source_kind": "europe_pmc_jats"}]}
                ],
            }

    class FakeService:
        async def retrieve_context_batch(self, review_id, request):
            return ResponseWithTrace()

    result = await retrieve_review_context_batch_impl(
        service=FakeService(),
        review_id="review-1",
        queries=["MEFV"],
        include_resolver_trace=False,
    )

    assert "resolver_attempts" not in result
    assert "resolver_attempts" not in result["sources"][0]


@pytest.mark.asyncio
async def test_retrieve_review_context_batch_adapter_normalizes_llm_input_mistakes() -> None:
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl
    from pubtator_link.models.review_rerag import (
        ContextPack,
        PreparationStatus,
        RetrieveReviewContextBatchResponse,
    )

    captured_request = None

    class Service:
        async def retrieve_context_batch(self, review_id, request):
            nonlocal captured_request
            captured_request = request
            return RetrieveReviewContextBatchResponse(
                review_id=review_id,
                response_mode="compact",
                results=[],
                merged_context_pack=ContextPack(question="", passages=[], citation_map={}),
                preparation_status=PreparationStatus(),
            )

    result = await retrieve_review_context_batch_impl(
        service=Service(),
        review_id="r1",
        queries="MEFV",
        response_mode="Quotes",
        limit=3,
    )

    assert result["_meta"]["normalized_arguments"]
    assert captured_request.queries == ["MEFV"]
    assert captured_request.response_mode == "quotes"
    assert captured_request.max_total_passages == 3


@pytest.mark.asyncio
async def test_retrieve_review_context_batch_adapter_coerces_numeric_strings_before_budgeting() -> (
    None
):
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl
    from pubtator_link.models.review_rerag import (
        ContextPack,
        PreparationStatus,
        RetrieveReviewContextBatchResponse,
    )

    captured_request = None

    class Service:
        async def retrieve_context_batch(self, review_id, request):
            nonlocal captured_request
            captured_request = request
            return RetrieveReviewContextBatchResponse(
                review_id=review_id,
                response_mode="compact",
                results=[],
                merged_context_pack=ContextPack(question="", passages=[], citation_map={}),
                preparation_status=PreparationStatus(),
                budget_source=getattr(request, "budget_source", None),
            )

    result = await retrieve_review_context_batch_impl(
        service=Service(),
        review_id="r1",
        queries=["MEFV"],
        limit="14",
        max_chars_per_passage="2200",
    )

    assert captured_request.max_total_passages == 14
    assert captured_request.max_chars == 30_800
    assert captured_request.max_response_chars == 61_600
    assert result["budget_source"] == "auto_fit"


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["limit", "size"])
async def test_retrieve_review_context_batch_adapter_rejects_ambiguous_limit_alias(
    alias: str,
) -> None:
    from pubtator_link.mcp.input_normalization import InputNormalizationError
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl

    class Service:
        async def retrieve_context_batch(self, review_id, request):
            raise AssertionError("service should not be called for ambiguous arguments")

    with pytest.raises(InputNormalizationError) as error:
        await retrieve_review_context_batch_impl(
            service=Service(),
            review_id="r1",
            queries=["MEFV"],
            max_total_passages=5,
            **{alias: 3},
        )

    assert error.value.field_errors[0]["field"] == "max_total_passages"


@pytest.mark.asyncio
async def test_retrieve_review_context_batch_adapter_validates_quotes_numeric_bounds() -> None:
    from pydantic import ValidationError

    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl

    class Service:
        async def retrieve_context_batch(self, review_id, request):
            raise AssertionError("service should not be called for invalid arguments")

    with pytest.raises(ValidationError):
        await retrieve_review_context_batch_impl(
            service=Service(),
            review_id="r1",
            queries=["MEFV"],
            response_mode="Quotes",
            max_total_passages=999,
        )


@pytest.mark.asyncio
async def test_retrieve_review_context_batch_adapter_constructs_quotes_request_directly(
    monkeypatch,
) -> None:
    from pubtator_link.mcp import service_adapters
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl
    from pubtator_link.models.review_rerag import (
        ContextPack,
        PreparationStatus,
        RetrieveReviewContextBatchRequest,
        RetrieveReviewContextBatchResponse,
    )

    constructed_modes: list[str] = []

    class RecordingRequest(RetrieveReviewContextBatchRequest):
        def __init__(self, **data):
            constructed_modes.append(data["response_mode"])
            super().__init__(**data)

    class Service:
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

    monkeypatch.setattr(service_adapters, "RetrieveReviewContextBatchRequest", RecordingRequest)
    service = Service()

    await retrieve_review_context_batch_impl(
        service=service,
        review_id="r1",
        queries=["MEFV"],
        response_mode="Quotes",
    )

    assert constructed_modes == ["quotes"]
    assert service.request.response_mode == "quotes"


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
                index_snapshot_date="2026-05-02",
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
    assert result["index_snapshot_date"] is not None


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
                response_mode=request.response_mode,
                preparation_status=PreparationStatus(complete=1),
                sources=[],
                totals=ReviewIndexTotals(),
                failed_sources=[],
                index_snapshot_date="2026-05-02",
            )

    service = RecordingService()

    result = await inspect_review_index_impl(
        service=service,
        review_id="rev",
        pmids=["40234174"],
        include_passage_samples=True,
        sample_per_pmid=3,
        min_sample_chars=120,
        sample_section_policy="original_order",
        response_mode="compact",
    )

    assert service.review_id == "rev"
    assert service.request.pmids == ["40234174"]
    assert service.request.sample_per_pmid == 3
    assert service.request.min_sample_chars == 120
    assert service.request.sample_section_policy == "original_order"
    assert service.request.response_mode == "compact"
    assert result["response_mode"] == "compact"
    assert result["review_id"] == "rev"
    assert result["index_snapshot_date"] is not None


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
async def test_search_literature_meta_uses_short_next_tool_hints() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "results": [{"pmid": "1", "title": "FMF guideline"}],
                "count": 1,
                "total_pages": 1,
                "page_size": 10,
            }

    result = await search_literature_impl(client=FakeClient(), text="FMF")

    meta = result["_meta"]
    assert meta["next_tools"] == [
        "pubtator.preflight_review_sources",
        "pubtator.index_review_evidence",
    ]
    assert meta["workflow"] == "search -> preflight -> index -> inspect -> retrieve"
    assert meta["details_resource"] == "pubtator://workflow-help"
    assert "next_commands" not in meta


@pytest.mark.asyncio
async def test_search_literature_default_does_not_require_preflight_service() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {"results": [{"pmid": "123", "title": "MEFV colchicine"}], "count": 1}

    class ExplodingPreflight:
        async def preflight_pmids(self, pmids):
            raise RuntimeError("review database unavailable")

    result = await search_literature_impl(
        client=FakeClient(),
        text="MEFV colchicine",
        coverage="none",
        preflight_service=ExplodingPreflight(),
        metadata="none",
        metadata_service=None,
    )

    assert result["success"] is True
    assert result["results"]
    assert "review database unavailable" not in str(result).lower()
    assert result["_meta"]["coverage_note"].startswith("Search is read-only metadata discovery.")
    assert result["_meta"]["next_tools"] == [
        "pubtator.preflight_review_sources",
        "pubtator.index_review_evidence",
    ]
    assert "next_commands" not in result["_meta"]


@pytest.mark.asyncio
async def test_search_literature_attaches_preflight_coverage() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl
    from pubtator_link.models.review_rerag import SourceCoverageHint

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "results": [{"pmid": "39540697", "title": "FMF in Childhood"}],
                "count": 1,
                "total_pages": 1,
                "page_size": 10,
            }

    class FakePreflight:
        async def preflight_pmids(self, pmids: list[str]) -> list[SourceCoverageHint]:
            return [
                SourceCoverageHint(
                    pmid="39540697",
                    expected_coverage="abstract_only",
                    coverage_reason="no_pmcid",
                )
            ]

    result = await search_literature_impl(
        client=FakeClient(),
        text="FMF",
        coverage="preflight",
        preflight_service=FakePreflight(),
    )

    assert result["results"][0]["coverage_hint"]["expected_coverage"] == "abstract_only"


@pytest.mark.asyncio
async def test_search_literature_impl_enriches_basic_metadata() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl
    from pubtator_link.models.publication_metadata import (
        PublicationAuthor,
        PublicationMetadata,
        PublicationMetadataResponse,
    )

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "results": [{"pmid": "33454820", "title": "FMF"}],
                "count": 1,
                "total_pages": 1,
                "page_size": 10,
            }

    class FakeMetadata:
        async def get_metadata(self, request):
            assert request.pmids == ["33454820"]
            return PublicationMetadataResponse(
                metadata=[
                    PublicationMetadata(
                        pmid="33454820",
                        authors=[PublicationAuthor(last_name="Kavrul Kayaalp", initials="GK")],
                    )
                ],
                _meta={"next_commands": []},
            )

    result = await search_literature_impl(
        client=FakeClient(),
        text="MEFV",
        metadata="basic",
        metadata_service=FakeMetadata(),
    )

    assert result["results"][0]["authors"] == []
    assert result["results"][0]["first_author_et_al"] == "Kavrul Kayaalp GK"


@pytest.mark.asyncio
async def test_search_literature_metadata_respects_limit() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl
    from pubtator_link.models.publication_metadata import PublicationMetadataResponse

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "results": [
                    {"pmid": "1", "title": "First"},
                    {"pmid": "2", "title": "Second"},
                ],
                "count": 2,
                "total_pages": 1,
                "page_size": 10,
            }

    class FakeMetadata:
        async def get_metadata(self, request):
            assert request.pmids == ["1"]
            return PublicationMetadataResponse(metadata=[], _meta={"next_commands": []})

    result = await search_literature_impl(
        client=FakeClient(),
        text="MEFV",
        limit=1,
        metadata="basic",
        metadata_service=FakeMetadata(),
    )

    assert [item["pmid"] for item in result["results"]] == ["1"]


@pytest.mark.asyncio
async def test_search_literature_full_metadata_requests_citations() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl
    from pubtator_link.models.publication_metadata import PublicationMetadataResponse

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "results": [{"pmid": "33454820", "title": "FMF"}],
                "count": 1,
                "total_pages": 1,
                "page_size": 10,
            }

    class FakeMetadata:
        async def get_metadata(self, request):
            assert request.include_mesh is True
            assert request.include_citations == "both"
            return PublicationMetadataResponse(metadata=[], _meta={"next_commands": []})

    await search_literature_impl(
        client=FakeClient(),
        text="MEFV",
        metadata="full",
        metadata_service=FakeMetadata(),
    )


@pytest.mark.asyncio
async def test_search_entities_derives_matched_terms_from_match_text() -> None:
    from pubtator_link.mcp.service_adapters import search_biomedical_entities_impl

    class FakeClient:
        async def autocomplete_entity(self, query: str, concept: str | None, limit: int):
            return [
                {
                    "_id": "@DISEASE_FMF",
                    "name": "Familial Mediterranean Fever",
                    "biotype": "Disease",
                    "match": "Matched on synonyms <m>FMF, periodic fever</m>",
                }
            ]

    result = await search_biomedical_entities_impl(
        client=FakeClient(),
        query="FMF",
        concept="Disease",
    )

    assert result["matches"][0]["matched_terms"] == ["FMF", "periodic fever"]


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

    result = await search_literature_impl(
        client=FakeClient(),
        text="guideline",
        include_citations="nlm",
    )

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
async def test_search_literature_compact_omits_bibtex_and_plainifies_text_hl() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "results": [
                    {
                        "pmid": "1",
                        "title": "FMF guideline",
                        "journal": "Ann Rheum Dis",
                        "date": "2025-01-01T00:00:00Z",
                        "text_hl": "@GENE_MEFV @@@MEFV@@@ in @DISEASE_FMF @@@FMF@@@",
                        "citations": {"NLM": "NLM citation", "BibTeX": "@article{x}"},
                    }
                ],
                "count": 1,
                "total_pages": 1,
                "page_size": 10,
            }

    result = await search_literature_impl(
        client=FakeClient(),
        text="FMF",
        include_citations="nlm",
        text_hl_format="plain",
        limit=5,
    )

    first = result["results"][0]
    assert first["text_hl"] == "MEFV in FMF"
    assert first["citations"] == {"NLM": "NLM citation"}
    assert "BibTeX" not in first["citations"]


@pytest.mark.asyncio
async def test_search_literature_combines_entity_ids_with_text() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    captured = {}

    class FakeClient:
        async def search_publications(self, **kwargs):
            captured.update(kwargs)
            return {"results": [], "count": 0, "total_pages": 0, "page_size": 10}

    await search_literature_impl(
        client=FakeClient(),
        text="colchicine",
        entity_ids=["@GENE_MEFV", "@DISEASE_FMF"],
    )

    assert captured["text"] == "(colchicine) AND @GENE_MEFV AND @DISEASE_FMF"


@pytest.mark.asyncio
async def test_search_literature_guideline_boost_reranks_page() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "results": [
                    {"pmid": "1", "title": "Narrative review", "score": 10.0},
                    {
                        "pmid": "2",
                        "title": "EULAR recommendations for FMF",
                        "score": 5.0,
                        "publication_types": ["Practice Guideline"],
                    },
                ],
                "count": 2,
                "total_pages": 1,
                "page_size": 10,
            }

    result = await search_literature_impl(
        client=FakeClient(),
        text="FMF",
        guideline_boost=True,
        response_mode="full",
    )

    assert [item["pmid"] for item in result["results"]] == ["2", "1"]
    assert result["results"][0]["rank_features"]["guideline_boost"] > 0


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
async def test_get_publication_passages_adapter_passes_dry_run_and_verbosity() -> None:
    from pubtator_link.mcp.service_adapters import get_publication_passages_impl
    from pubtator_link.models.publication_passages import (
        PublicationContextEstimate,
        PublicationPassageResponse,
    )

    class RecordingPublicationPassageService:
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
                    sections_by_pmid={"111": []},
                    recommended_mode="compact_passages",
                    warning=None,
                ),
            )

    service = RecordingPublicationPassageService()

    await get_publication_passages_impl(
        service=service,
        pmids=["111"],
        dry_run=True,
        verbosity="lean",
    )

    assert service.request.dry_run is True
    assert service.request.verbosity == "lean"


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
async def test_lookup_variant_evidence_adapter_calls_service() -> None:
    from pubtator_link.mcp.service_adapters import lookup_variant_evidence_impl
    from pubtator_link.models.variants import VariantEvidenceResponse

    class FakeVariantEvidenceService:
        async def lookup(self, request):
            return VariantEvidenceResponse(query=request.model_dump(exclude_none=True))

    response = await lookup_variant_evidence_impl(
        gene="MEFV",
        variant="c.2177T>C",
        service=FakeVariantEvidenceService(),
    )

    assert response["query"]["gene"] == "MEFV"


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


async def test_citation_graph_adapter_accepts_compact_response_mode() -> None:
    from pubtator_link.mcp.service_adapters import get_publication_citation_graph_impl
    from pubtator_link.models.literature_graph import (
        LiteraturePaper,
        PublicationCitationGraphResponse,
    )

    class Service:
        async def get_citation_graph(self, request):
            assert request.response_mode == "compact"
            return PublicationCitationGraphResponse(
                source=LiteraturePaper(pmid="1"),
                response_mode="compact",
            )

    result = await get_publication_citation_graph_impl(
        service=Service(),
        pmid="1",
        response_mode="compact",
    )

    assert result["response_mode"] == "compact"
