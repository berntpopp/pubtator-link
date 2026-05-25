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


def test_strip_meta_for_repeated_call_removes_diagnostics_and_preserves_answer_content() -> None:
    from pubtator_link.mcp.meta_budget import strip_meta_for_repeated_call

    payload = {
        "success": True,
        "_meta": {"next_commands": ["pubtator_retrieve_review_context_batch"]},
        "provider_status": [{"provider": "pubmed", "status": "success"}],
        "results": [
            {
                "pmid": "40234174",
                "title": "Colchicine response in FMF",
                "citation": "PMID:40234174",
                "passage_id": "rev:40234174:abstract:0",
                "text": "Colchicine reduced attacks.",
                "coverage_hint": "full_text",
                "unsafe_for_clinical_use": True,
                "_meta": {"debug": True},
                "rrf_score": 0.5,
                "lexical_rank_position": 1,
                "dense_rank_position": 2,
                "rank_features": {"guideline_boost": 1.0},
                "provider_status": [{"provider": "dense", "status": "success"}],
                "score_explanation": "dense neighbor score",
                "match_reasons": ["entity_overlap"],
                "omitted_candidate_preview": [{"pmid": "1"}],
                "abstract": None,
                "mesh_headings": [],
            }
        ],
    }

    stripped = strip_meta_for_repeated_call(payload)

    assert "_meta" not in stripped
    assert "provider_status" not in stripped
    assert stripped["results"][0] == {
        "pmid": "40234174",
        "title": "Colchicine response in FMF",
        "citation": "PMID:40234174",
        "passage_id": "rev:40234174:abstract:0",
        "text": "Colchicine reduced attacks.",
        "coverage_hint": "full_text",
        "unsafe_for_clinical_use": True,
    }
    assert "_meta" in payload
    assert "rrf_score" in payload["results"][0]


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
async def test_get_publication_metadata_impl_preserves_public_100_pmid_cap() -> None:
    from pydantic import ValidationError

    from pubtator_link.mcp import service_adapters

    class UnexpectedService:
        async def get_metadata(self, request):
            raise AssertionError("oversized public metadata request should fail validation first")

    with pytest.raises(ValidationError) as exc_info:
        await service_adapters.get_publication_metadata_impl(
            service=UnexpectedService(),
            pmids=[str(600000 + index) for index in range(101)],
            include_mesh=True,
            include_publication_types=True,
            include_citations="both",
            include_coverage=True,
        )
    assert exc_info.value.errors()[0]["loc"] == ("pmids",)
    assert exc_info.value.errors()[0]["type"] == "too_long"


@pytest.mark.asyncio
async def test_graph_adapters_default_omitted_response_mode_to_compact() -> None:
    from pubtator_link.mcp.service_adapters import (
        build_topic_literature_map_impl,
        find_related_evidence_candidates_impl,
        get_publication_citation_graph_impl,
    )
    from pubtator_link.models.literature_graph import (
        LiteraturePaper,
        PublicationCitationGraphResponse,
        RelatedEvidenceCandidatesResponse,
        TopicLiteratureMapResponse,
    )

    class CitationService:
        request = None

        async def get_citation_graph(self, request):
            self.request = request
            return PublicationCitationGraphResponse(
                source=LiteraturePaper(pmid="1"),
                response_mode=request.response_mode,
            )

    class RelatedService:
        request = None

        async def find_candidates(self, request):
            self.request = request
            return RelatedEvidenceCandidatesResponse(
                source=LiteraturePaper(pmid=request.pmid),
                meta={"response_mode": request.response_mode},
            )

    class TopicService:
        request = None

        async def build_map(self, request):
            self.request = request
            return TopicLiteratureMapResponse(
                query=request.query,
                response_mode=request.response_mode,
            )

    citation = CitationService()
    related = RelatedService()
    topic = TopicService()

    citation_result = await get_publication_citation_graph_impl(
        service=citation,
        pmid="1",
    )
    related_result = await find_related_evidence_candidates_impl(
        service=related,
        pmid="1",
    )
    topic_result = await build_topic_literature_map_impl(
        service=topic,
        query="FMF",
        timeout_ms=1234,
        citation_graph_timeout_ms=100,
        related_evidence_timeout_ms=200,
        metadata_backfill_timeout_ms=300,
    )

    assert citation.request.response_mode == "compact"
    assert related.request.response_mode == "compact"
    assert topic.request.response_mode == "compact"
    assert topic.request.timeout_ms == 1234
    assert topic.request.citation_graph_timeout_ms == 100
    assert topic.request.related_evidence_timeout_ms == 200
    assert topic.request.metadata_backfill_timeout_ms == 300
    assert citation_result["response_mode"] == "compact"
    assert related_result["_meta"]["response_mode"] == "compact"
    assert topic_result["response_mode"] == "compact"
    assert "response_mode_deprecation" not in str(citation_result)
    assert "response_mode_deprecation" not in str(related_result)
    assert "response_mode_deprecation" not in str(topic_result)


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
async def test_inspect_review_index_adapter_wires_limit_cursor_and_next_command() -> None:
    from pubtator_link.mcp.service_adapters import inspect_review_index_impl
    from pubtator_link.models.review_rerag import (
        InspectReviewIndexResponse,
        PreparationStatus,
        ReviewIndexTotals,
    )

    class RecordingService:
        request = None

        async def inspect_review_index(self, review_id, request):
            self.request = request
            return InspectReviewIndexResponse(
                review_id=review_id,
                response_mode=request.response_mode,
                preparation_status=PreparationStatus(complete=1),
                sources=[],
                totals=ReviewIndexTotals(source_count=2),
                failed_sources=[],
                next_cursor="cursor-2",
                page_source_count=1,
                omitted_counts={"sources": 1},
            )

    service = RecordingService()

    result = await inspect_review_index_impl(
        service=service,
        review_id="review-1",
        response_mode="compact",
        limit=1,
        cursor="cursor-1",
    )

    assert service.request.limit == 1
    assert service.request.cursor == "cursor-1"
    assert result["next_cursor"] == "cursor-2"
    assert result["_meta"]["next_commands"][0]["tool"] == "pubtator_inspect_review_index"
    assert result["_meta"]["next_commands"][0]["arguments"]["cursor"] == "cursor-2"


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
        response_mode="full",
    )

    assert set(result) == {"success", "audit_bundle"}
    assert result["success"] is True
    assert result["audit_bundle"]["review_id"] == "rev_123"
    assert result["audit_bundle"]["index_snapshot_date"] is not None


@pytest.mark.asyncio
async def test_export_review_audit_bundle_adapter_returns_compact_summary() -> None:
    from pubtator_link.mcp.service_adapters import export_review_audit_bundle_impl

    result = await export_review_audit_bundle_impl(
        service=_FakeReviewAuditBundleService(),
        review_id="rev_123",
        response_mode="compact",
    )

    assert result["success"] is True
    assert "audit_bundle" not in result
    assert result["audit_bundle_summary"]["review_id"] == "rev_123"
    assert result["audit_bundle_summary"]["passage_id_count"] >= 0
    assert "stable_citation_keys" in result["audit_bundle_summary"]["omitted_fields"]


@pytest.mark.asyncio
async def test_export_review_audit_bundle_adapter_defaults_to_compact_summary() -> None:
    from pubtator_link.mcp.service_adapters import export_review_audit_bundle_impl

    result = await export_review_audit_bundle_impl(
        service=_FakeReviewAuditBundleService(),
        review_id="rev_123",
    )

    assert "audit_bundle_summary" in result
    assert "audit_bundle" not in result


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
                _meta={"next_commands": ["pubtator_index_review_evidence"]},
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
    assert result["_meta"]["next_commands"] == ["pubtator_index_review_evidence"]


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
                meta={"next_commands": ["pubtator_retrieve_review_context_batch"]},
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
    assert result["next_commands"][0] == "pubtator_retrieve_review_context_batch"


@pytest.mark.asyncio
async def test_review_quickstart_adapter_honors_wait_until_ready() -> None:
    from pubtator_link.mcp.service_adapters import review_quickstart_impl
    from pubtator_link.models.review_rerag import (
        InspectReviewIndexResponse,
        PreparationStatus,
        ResearchSessionCandidate,
        ResearchSessionManifest,
        ReviewIndexTotals,
        StageResearchSessionResponse,
    )

    captured: dict[str, object] = {}

    class Queue:
        repository = object()

    class StageService:
        queue = Queue()

        async def stage(self, *, review_id, request):
            return StageResearchSessionResponse(
                manifest=ResearchSessionManifest(
                    session_id="session-1",
                    review_id=review_id,
                    query=request.query,
                    candidate_count=1,
                    candidates=[ResearchSessionCandidate(pmid="24166952", rank=1)],
                ),
                meta={},
            )

    class ContextService:
        async def inspect_review_index(self, review_id, request):
            return InspectReviewIndexResponse(
                review_id=review_id,
                preparation_status=PreparationStatus(complete=0),
                sources=[],
                totals=ReviewIndexTotals(pmid_count=1, source_count=1, passage_count=0),
                failed_sources=[],
            )

    class IndexingService:
        def __init__(self, *, repository, queue):
            captured["repository"] = repository
            captured["queue"] = queue

        async def index_review_evidence(self, review_id, request):
            captured["review_id"] = review_id
            captured["request"] = request

    result = await review_quickstart_impl(
        stage_service=StageService(),
        context_service=ContextService(),
        topic="MEFV colchicine",
        wait_until_ready=True,
        timeout_ms=30_000,
        review_indexing_service_factory=IndexingService,
    )

    request = captured["request"]
    assert request.wait_for_completion is True
    assert request.wait_for_status == "complete_or_partial"
    assert request.timeout_ms == 30_000
    assert request.pmids == ["24166952"]
    assert "quickstart does not block on indexing" not in result["warnings"]


@pytest.mark.asyncio
async def test_list_research_sessions_adapter_uses_global_path_without_review_id() -> None:
    from pubtator_link.mcp.service_adapters import list_research_sessions_impl
    from pubtator_link.models.review_rerag import (
        ListResearchSessionsResponse,
        ResearchSessionManifest,
    )

    class Service:
        local_calls = 0
        global_calls = 0

        async def list_sessions(self, *, review_id):
            self.local_calls += 1
            raise AssertionError("review-scoped path should not be used")

        async def list_sessions_global(self, *, limit=20):
            self.global_calls += 1
            assert limit == 20
            return ListResearchSessionsResponse(
                sessions=[
                    ResearchSessionManifest(
                        review_id="review-2",
                        session_id="session-2",
                        updated_at="2026-05-02T00:00:00Z",
                    ),
                ]
            )

    service = Service()

    result = await list_research_sessions_impl(service=service, review_id=None)

    assert result["success"] is True
    assert result["sessions"][0]["review_id"] == "review-2"
    assert service.local_calls == 0
    assert service.global_calls == 1


@pytest.mark.asyncio
async def test_get_research_session_status_adapter_resolves_session_id_only() -> None:
    from pubtator_link.mcp.service_adapters import get_research_session_status_impl
    from pubtator_link.models.review_rerag import (
        ResearchSessionManifest,
        ResearchSessionStatusResponse,
    )

    class Service:
        async def get_status(self, *, review_id, session_id):
            raise AssertionError("review-scoped lookup should not be used")

        async def get_status_by_session_id(self, *, session_id):
            assert session_id == "session-1"
            return ResearchSessionStatusResponse(
                manifest=ResearchSessionManifest(
                    review_id="review-1",
                    session_id=session_id,
                )
            )

    result = await get_research_session_status_impl(
        service=Service(),
        review_id=None,
        session_id="session-1",
    )

    assert result["success"] is True
    assert result["manifest"]["review_id"] == "review-1"


@pytest.mark.asyncio
async def test_get_research_session_status_adapter_maps_session_id_only_errors() -> None:
    from pubtator_link.mcp.service_adapters import get_research_session_status_impl

    class NotFoundService:
        async def get_status_by_session_id(self, *, session_id):
            raise LookupError(f"Research session not found: {session_id}")

    class AmbiguousService:
        async def get_status_by_session_id(self, *, session_id):
            raise ValueError(f"Research session id is ambiguous: {session_id}")

    not_found = await get_research_session_status_impl(
        service=NotFoundService(),
        review_id=None,
        session_id="missing",
    )
    ambiguous = await get_research_session_status_impl(
        service=AmbiguousService(),
        review_id=None,
        session_id="session-1",
    )

    assert not_found["success"] is False
    assert not_found["error_code"] == "not_found"
    assert ambiguous["success"] is False
    assert ambiguous["error_code"] == "validation_failed"


async def _run_ground_question_fixture(service_adapters, **kwargs):
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
        **kwargs,
    )

    return result, context_service, indexing_services, queue


@pytest.mark.asyncio
async def test_ground_question_adapter_chains_search_index_inspect_retrieve() -> None:
    from pubtator_link.mcp import service_adapters

    result, context_service, indexing_services, queue = await _run_ground_question_fixture(
        service_adapters
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
        "pubtator_record_review_context",
        "pubtator_get_review_audit_trail",
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
async def test_ground_question_adapter_resolves_auto_budget_by_verbosity() -> None:
    from pubtator_link.mcp import service_adapters

    result, context_service, _indexing_services, _queue = await _run_ground_question_fixture(
        service_adapters,
        verbosity="standard",
        max_response_chars="auto",
    )

    assert result["success"] is True
    assert context_service.retrieve_request.max_response_chars == 24000
    assert context_service.retrieve_request.verbosity == "standard"


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
    assert result["next_tools"] == ["pubtator_search_literature"]
    assert result["recovery"] == [
        "Refine the search query or provide candidate PMIDs explicitly.",
    ]
    assert "_meta" not in result


@pytest.mark.asyncio
async def test_ground_question_long_natural_language_query_returns_warning() -> None:
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

    result = await service_adapters.ground_question_impl(
        client=FakeClient(),
        queue=FakeQueue(),
        context_service=FakeContextService(),
        question=(
            "What are the best practices for treating a child with a variant of "
            "uncertain significance in MEFV when considering colchicine and monitoring?"
        ),
        max_pmids=8,
        review_indexing_service_factory=lambda **kwargs: None,
    )

    assert result["query_length_warning"] == (
        "Long natural-language question used for search; consider splitting into 6 or fewer key terms."
    )


@pytest.mark.asyncio
async def test_ground_question_long_query_attempts_shortened_variant_before_recovery() -> None:
    from pubtator_link.mcp import service_adapters

    class FakeClient:
        def __init__(self) -> None:
            self.queries: list[str] = []

        async def search_publications(self, **kwargs):
            self.queries.append(kwargs["text"])
            return {"count": 0, "page": 1, "results": []}

    class FakeQueue:
        repository = object()

    class FakeContextService:
        async def inspect_review_index(self, review_id, request):
            raise AssertionError("inspect should not be called without selected PMIDs")

        async def retrieve_context_batch(self, review_id, request):
            raise AssertionError("retrieve should not be called without selected PMIDs")

    client = FakeClient()
    question = (
        "What are the best practices for treating a child with a variant of "
        "uncertain significance in MEFV when considering colchicine and monitoring?"
    )

    result = await service_adapters.ground_question_impl(
        client=client,
        queue=FakeQueue(),
        context_service=FakeContextService(),
        question=question,
        max_pmids=8,
        review_indexing_service_factory=lambda **kwargs: None,
    )

    assert len(client.queries) >= 2
    assert client.queries[0] == question
    assert all("What are the best practices" not in query for query in client.queries[1:])
    assert result["query_variants_attempted"] == client.queries
    assert result["recovery"] == [
        "Refine the search query or provide candidate PMIDs explicitly.",
    ]


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
        "pubtator_inspect_review_index",
        "pubtator_retrieve_review_context_batch",
    ]


@pytest.mark.asyncio
async def test_index_review_evidence_adapter_returns_lifecycle_guidance() -> None:
    from pubtator_link.mcp.service_adapters import index_review_evidence_impl
    from pubtator_link.models.review_rerag import PreparationStatus

    class FakeRepository:
        async def preparation_job_statuses(self, review_id, source_ids):
            return {
                "PMID:40234175": "complete",
                "URL:https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7811395/": "complete",
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
        curated_urls=["https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7811395/"],
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
async def test_retrieve_review_context_batch_adapter_accepts_auto_budget_and_verbosity() -> None:
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
                budget_source=request.budget_source,
            )

    service = RecordingService()

    await retrieve_review_context_batch_impl(
        service=service,
        review_id="review-1",
        queries=["MEFV"],
        verbosity="full",
        max_response_chars="auto",
    )

    assert service.request.verbosity == "full"
    assert service.request.max_response_chars == 60000
    assert service.request.budget_source == "auto_fit"


@pytest.mark.asyncio
async def test_retrieve_review_context_batch_adapter_preserves_embedding_diagnostics() -> None:
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl
    from pubtator_link.models.review_rerag import (
        ContextPack,
        EmbeddingRerankDiagnostics,
        PreparationStatus,
        RetrieveReviewContextBatchResponse,
        RetrieveReviewContextResponse,
        RetrieveReviewDiagnostics,
    )

    class FakeService:
        async def retrieve_context_batch(self, review_id, request):
            return RetrieveReviewContextBatchResponse(
                review_id=review_id,
                results=[
                    RetrieveReviewContextResponse(
                        review_id=review_id,
                        context_pack=ContextPack(
                            question=request.queries[0],
                            passages=[],
                            citation_map={},
                        ),
                        preparation_status=PreparationStatus(complete=1),
                        diagnostics=RetrieveReviewDiagnostics(
                            query=request.queries[0],
                            query_tokens=["colchicine"],
                            candidate_count=2,
                            selected_count=1,
                            message="ok",
                            embedding_rerank=EmbeddingRerankDiagnostics(
                                enabled=True,
                                active=True,
                                model_name="BAAI/bge-small-en-v1.5",
                                embedding_dim=384,
                                candidate_count=2,
                                embedded_candidate_count=2,
                                strategy="lexical_top_k_dense_rrf",
                            ),
                        ),
                    )
                ],
                merged_context_pack=ContextPack(
                    question=request.queries[0],
                    passages=[],
                    citation_map={},
                ),
                preparation_status=PreparationStatus(complete=1),
                include_diagnostics=True,
            )

    result = await retrieve_review_context_batch_impl(
        service=FakeService(),
        review_id="rev_123",
        queries=["colchicine"],
        include_diagnostics=True,
    )

    embedding = result["results"][0]["diagnostics"]["embedding_rerank"]
    assert embedding["active"] is True
    assert embedding["model_name"] == "BAAI/bge-small-en-v1.5"
    assert embedding["strategy"] == "lexical_top_k_dense_rrf"


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
    assert service.request.max_response_chars == 24000
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
async def test_retrieve_review_context_batch_adapter_uses_auto_response_budget_with_explicit_chars() -> (
    None
):
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
    assert service.request.max_response_chars == 24_000
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
    assert captured_request.max_response_chars == 24_000
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
        "pubtator_preflight_review_sources",
        "pubtator_index_review_evidence",
    ]
    assert meta["workflow"] == "search -> preflight -> index -> inspect -> retrieve"
    assert meta["details_resource"] == "pubtator://workflow-help"
    assert "next_commands" not in meta


@pytest.mark.asyncio
async def test_search_literature_can_omit_meta_for_repeated_searches() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "results": [{"pmid": "1", "title": "FMF guideline"}],
                "count": 1,
                "total_pages": 1,
                "page_size": 10,
            }

    result = await search_literature_impl(
        client=FakeClient(),
        text="FMF",
        include_meta=False,
    )

    assert "_meta" not in result
    assert "cache_key" not in result
    assert "corpus_snapshot_date" not in result
    assert "source_versions" not in result


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
        "pubtator_preflight_review_sources",
        "pubtator_index_review_evidence",
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

    assert "authors" not in result["results"][0]
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
async def test_search_literature_metadata_batches_limit_none_over_public_cap() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl
    from pubtator_link.models.publication_metadata import (
        PublicationMetadata,
        PublicationMetadataResponse,
    )

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "results": [
                    {"pmid": str(pmid), "title": f"Search {pmid}"} for pmid in range(500000, 500105)
                ],
                "count": 105,
                "total_pages": 1,
                "page_size": 105,
            }

    class RecordingMetadata:
        def __init__(self) -> None:
            self.requests = []

        async def get_metadata(self, request):
            self.requests.append(request)
            return PublicationMetadataResponse(
                metadata=[
                    PublicationMetadata(pmid=pmid, title=f"Metadata {pmid}")
                    for pmid in request.pmids
                ],
                _meta={"next_commands": []},
            )

    metadata = RecordingMetadata()

    result = await search_literature_impl(
        client=FakeClient(),
        text="MEFV",
        limit=None,
        metadata="basic",
        metadata_service=metadata,
    )

    assert result["success"] is True
    assert len(result["results"]) == 105
    assert [len(request.pmids) for request in metadata.requests] == [100, 5]
    assert [request.include_mesh for request in metadata.requests] == [False, False]
    assert [request.include_citations for request in metadata.requests] == ["none", "none"]
    assert [request.include_coverage for request in metadata.requests] == [False, False]


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
async def test_search_literature_compact_omits_empty_and_null_optional_fields() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "results": [{"pmid": "1", "title": "FMF guideline"}],
                "count": 1,
                "total_pages": 1,
                "page_size": 10,
            }

    result = await search_literature_impl(
        client=FakeClient(),
        text="FMF",
        response_mode="compact",
        metadata="none",
        metadata_service=None,
    )

    first = result["results"][0]
    assert "abstract" not in first
    assert "annotations" not in first
    assert "mesh_headings" not in first
    assert "nlm_citation" not in first
    assert "bibtex" not in first


@pytest.mark.asyncio
async def test_search_literature_with_abstract_metadata_inlines_bounded_abstract() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    abstract = " ".join(["MEFV variant evidence in children."] * 80)

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "results": [{"pmid": "1", "title": "FMF guideline", "abstract": abstract}],
                "count": 1,
                "total_pages": 1,
                "page_size": 10,
            }

    result = await search_literature_impl(
        client=FakeClient(),
        text="FMF",
        response_mode="compact",
        metadata="with_abstract",
        metadata_service=None,
    )

    assert result["results"][0]["abstract"].startswith("MEFV variant evidence")
    assert len(result["results"][0]["abstract"]) <= 650


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
async def test_search_literature_retries_unfiltered_when_pubtator_filters_unavailable() -> None:
    from pubtator_link.api.client import PubTatorAPIError
    from pubtator_link.mcp.service_adapters import search_literature_impl

    class FilterUnavailableClient:
        def __init__(self) -> None:
            self.calls: list[str | None] = []

        async def search_publications(
            self,
            text: str,
            page: int,
            sort: str | None,
            filters: str | None,
            sections: str | None,
        ) -> dict[str, object]:
            self.calls.append(filters)
            if filters is not None:
                raise PubTatorAPIError(
                    'HTTP 400: {"detail":"We are currently updating the Database. '
                    'Please try again later"}',
                    status_code=400,
                )
            return {
                "results": [
                    {
                        "pmid": "1",
                        "title": "Older guideline",
                        "date": "2019-01-01T00:00:00Z",
                        "publication_types": ["Practice Guideline"],
                    },
                    {
                        "pmid": "2",
                        "title": "Recent guideline",
                        "date": "2023-01-01T00:00:00Z",
                        "publication_types": ["Practice Guideline"],
                    },
                    {
                        "pmid": "3",
                        "title": "Recent review",
                        "date": "2024-01-01T00:00:00Z",
                        "publication_types": ["Review"],
                    },
                ],
                "count": 3,
                "total_pages": 1,
                "page_size": 10,
            }

    client = FilterUnavailableClient()

    result = await search_literature_impl(
        client=client,
        text="CFTR",
        publication_types=["Practice Guideline"],
        year_min=2020,
        year_max=2026,
        metadata="none",
    )

    assert client.calls == [
        '{"type":["Practice Guideline"],"year":{"min":2020,"max":2026}}',
        None,
    ]
    assert [item["pmid"] for item in result["results"]] == ["2"]
    assert result["message"] == (
        "PubTator3 filtered search was unavailable; returned an unfiltered page "
        "with local best-effort filters applied."
    )
    assert result["source_versions"]["pubtator3_filtering"] == "local_fallback"


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
async def test_estimate_publication_context_adapter_returns_recommended_max_chars() -> None:
    from pubtator_link.mcp.service_adapters import estimate_publication_context_impl
    from pubtator_link.models.publication_passages import PublicationContextEstimateResponse

    class EstimateService:
        async def estimate_context(self, request):
            return PublicationContextEstimateResponse(
                pmids=request.pmids,
                mode=request.mode,
                estimated_passages=4,
                estimated_chars=10_000,
                sections_by_pmid={"29355051": ["abstract"]},
                recommended_mode="compact_passages",
            )

    result = await estimate_publication_context_impl(
        service=EstimateService(),
        pmids=["29355051"],
    )

    assert result["recommended_max_chars"] >= result["estimated_chars"]
    assert result["recommended_max_chars"] <= 50_000


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
async def test_pmc_adapter_reports_empty_document_coverage_reason() -> None:
    from pubtator_link.mcp.service_adapters import fetch_pmc_annotations_impl
    from pubtator_link.models.publications import BioCDocument

    class Result:
        format = "biocjson"
        documents: ClassVar[list[BioCDocument]] = [BioCDocument(id="PMC11911402")]

    class FakeService:
        async def export_pmc_publications_list(self, pmcids: list[str], format: str) -> Result:
            return Result()

    result = await fetch_pmc_annotations_impl(service=FakeService(), pmcids=["PMC11911402"])

    assert result["coverage_by_pmcid"] == {"PMC11911402": "unknown"}
    assert result["coverage_reason_by_pmcid"] == {"PMC11911402": "no_pmc_full_text_retrievable"}


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
async def test_relations_adapter_compact_mode_applies_budget_controls() -> None:
    from pubtator_link.mcp.service_adapters import find_entity_relations_impl

    class FakeClient:
        async def find_relations(
            self, e1: str, relation_type: str | None, e2: str | None
        ) -> list[dict[str, object]]:
            return [
                {
                    "target": f"@DISEASE_{index}",
                    "type": "associate",
                    "pmids": [str(1000 + index), str(2000 + index)],
                    "publications": index,
                }
                for index in range(5)
            ]

    result = await find_entity_relations_impl(
        client=FakeClient(),
        entity_id="@GENE_MEFV",
        limit=2,
        response_mode="compact",
        max_response_chars=12000,
    )

    assert result["success"] is True
    assert len(result["related_entities"]) == 2
    assert result["omitted_count"] == 3
    assert result["response_size_class"] == "compact"
    assert result["related_entities"][0]["pmids"] == []
    assert result["related_entities"][0]["publications"] == 0


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
async def test_submit_text_annotation_adapter_waits_for_completed_result() -> None:
    from pubtator_link.mcp.service_adapters import submit_text_annotation_impl

    class FakeClient:
        async def submit_text_annotation(self, text: str, bioconcept: str) -> str:
            return "ABC123DEF456"

        async def retrieve_text_annotation(self, session_id: str) -> dict[str, object]:
            return {
                "status": "completed",
                "original_text": "MEFV and colchicine",
                "bioconcept": "Gene",
                "annotations": [
                    {
                        "start": 0,
                        "end": 4,
                        "text": "MEFV",
                        "entity_id": "@GENE_4210",
                        "entity_type": "Gene",
                    }
                ],
            }

        async def retrieve_text_annotation_until_ready(
            self, session_id: str, timeout_ms: int = 30000
        ) -> dict[str, object] | None:
            return await self.retrieve_text_annotation(session_id)

    result = await submit_text_annotation_impl(
        client=FakeClient(),
        text="MEFV and colchicine",
        bioconcepts="Gene",
        wait=True,
    )

    assert result["success"] is True
    assert result["status"] == "completed"
    assert result["annotations"][0]["entity_id"] == "@GENE_4210"


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
