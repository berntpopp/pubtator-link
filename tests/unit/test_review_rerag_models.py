import pytest
from pydantic import ValidationError

from pubtator_link.models.review_rerag import (
    ContextBudget,
    ContextPack,
    ContextPassage,
    EvidenceTier,
    IndexReviewEvidenceRequest,
    ListReviewIndexesResponse,
    McpReviewAuditBundleResponse,
    PreparationStatus,
    QueryDiagnosticsSummary,
    ResolverAttemptSummary,
    ReviewAuditBundle,
    ReviewIndexInventoryItem,
    ReviewIndexTotals,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextRequest,
    SourceCoverageHint,
    coverage_to_evidence_tier,
    normalize_section,
    passage_id_for_pmid,
)


def test_index_request_rejects_screened_mode() -> None:
    with pytest.raises(ValidationError):
        IndexReviewEvidenceRequest(pmids=["40234174"], prepare_mode="screened")


def test_context_request_defaults_are_poc_values() -> None:
    request = RetrieveReviewContextRequest(question="Should colchicine treat FMF?")

    assert request.max_passages == 8
    assert request.max_chars == 6000
    assert request.max_passages_per_pmid == 2


def test_passage_id_generation_is_deterministic() -> None:
    assert normalize_section("Methods & Results") == "methods_results"
    assert passage_id_for_pmid("40234174", "Methods & Results", 3) == (
        "PMID:40234174:methods_results:3"
    )


def test_context_pack_citation_map_uses_passage_ids() -> None:
    passage = ContextPassage(
        citation_key="S1",
        passage_id="PMID:40234174:abstract:0",
        pmid="40234174",
        section="abstract",
        text="Colchicine should start after clinical diagnosis.",
    )
    pack = ContextPack(
        question="When should colchicine start?",
        passages=[passage],
        citation_map={"S1": "PMID:40234174:abstract:0"},
    )

    assert pack.citation_map["S1"] == pack.passages[0].passage_id


def test_preparation_status_counts_terms() -> None:
    status = PreparationStatus(queued=1, running=2, complete=3, partial=4, failed=5)

    assert status.running == 2
    assert status.partial == 4


def test_batch_request_defaults_to_compact_context_safe_mode() -> None:
    request = RetrieveReviewContextBatchRequest(queries=["MEFV colchicine"])

    assert request.response_mode == "compact"
    assert request.max_response_chars == 24000
    assert request.allow_truncated_passages is True
    assert request.max_chars_per_passage == 2200
    assert request.include_tables is False
    assert request.include_references is False
    assert request.table_mode == "preview"


def test_context_pack_budget_metadata_defaults() -> None:
    budget = ContextBudget(
        max_chars=12000,
        text_chars=1000,
        estimated_json_chars=1500,
        estimated_total_chars=2500,
        estimated_tokens=695,
    )
    passage = ContextPassage(
        citation_key="S1",
        passage_id="PMID:1:abstract:0",
        pmid="1",
        section="ABSTRACT",
        text="Evidence text",
        char_count=13,
        start_char=0,
        end_char=13,
        boundary="full_passage",
    )
    pack = ContextPack(
        question="MEFV",
        passages=[passage],
        citation_map={"S1": "PMID:1:abstract:0"},
        total_chars=13,
        estimated_tokens=4,
        budget=budget,
    )

    assert pack.passages[0].truncated is False
    assert pack.budget is not None
    assert pack.budget.estimated_total_chars == 2500
    assert pack.dropped == []


def test_batch_summary_has_no_passage_text() -> None:
    summary = QueryDiagnosticsSummary(
        query="MEFV colchicine",
        query_tokens=["mefv", "colchicine"],
        candidate_count=3,
        selected_count=2,
        returned_count=1,
        dropped_count=1,
        top_sections=["ABSTRACT"],
        top_pmids=["123"],
        suggested_queries=["MEFV", "colchicine"],
    )

    assert "text" not in summary.model_dump()
    assert summary.zero_result_reason is None


def test_context_passage_generates_stable_citation_key() -> None:
    from pubtator_link.models.review_rerag import ContextPassage

    passage = ContextPassage(
        citation_key="S1",
        passage_id="PMID:40234174:abstract:1",
        pmid="40234174",
        section="ABSTRACT",
        text="Evidence text.",
    )

    assert passage.stable_citation_key.startswith("c_")
    assert len(passage.stable_citation_key) == 12
    assert (
        passage.stable_citation_key
        == ContextPassage(
            citation_key="S9",
            passage_id="PMID:40234174:abstract:1",
            pmid="40234174",
            section="ABSTRACT",
            text="Different response ordering.",
        ).stable_citation_key
    )


def test_context_pack_generates_stable_citation_map() -> None:
    from pubtator_link.models.review_rerag import ContextPack, ContextPassage

    passage = ContextPassage(
        citation_key="S1",
        passage_id="PMID:40234174:abstract:1",
        section="ABSTRACT",
        text="Evidence text.",
    )
    pack = ContextPack(
        question="FMF",
        passages=[passage],
        citation_map={"S1": passage.passage_id},
    )

    assert pack.stable_citation_map == {passage.stable_citation_key: "PMID:40234174:abstract:1"}


def test_source_coverage_hint_defaults_to_unknown_reason() -> None:
    hint = SourceCoverageHint(pmid="40234174")

    assert hint.expected_coverage == "unknown"
    assert hint.coverage_reason == "unknown"
    assert hint.pmc_fallback_available is False
    assert hint.resolver_attempts == []


def test_resolver_attempt_summary_captures_retry_metadata() -> None:
    attempt = ResolverAttemptSummary(
        source_kind="pubtator_full_bioc",
        status="failed",
        attempt_count=3,
        last_status_code=503,
        retry_after_ms=1000,
        backoff_ms=750,
        terminal_reason="retry_exhausted",
    )

    assert attempt.attempt_count == 3
    assert attempt.last_status_code == 503
    assert attempt.terminal_reason == "retry_exhausted"


def test_mcp_review_audit_bundle_response_preserves_existing_wrapper_shape() -> None:
    bundle = ReviewAuditBundle(
        review_id="review-1",
        generated_at="2026-05-01T00:00:00Z",
        preparation_status=PreparationStatus(complete=1),
        totals=ReviewIndexTotals(pmid_count=1, source_count=1, passage_count=0),
        sources=[],
        failed_sources=[],
        coverage_distribution={"full_text": 1},
        resolver_attempts=[],
        passage_ids=[],
        stable_citation_keys={},
    )

    dumped = McpReviewAuditBundleResponse(audit_bundle=bundle).model_dump(mode="json")

    assert set(dumped) == {"success", "audit_bundle"}
    assert dumped["success"] is True
    assert dumped["audit_bundle"]["review_id"] == "review-1"


def test_review_index_inventory_item_defaults_are_safe() -> None:
    item = ReviewIndexInventoryItem(
        review_id="review-1",
        created_at="2026-05-01T00:00:00Z",
        updated_at="2026-05-01T00:00:00Z",
        preparation_status=PreparationStatus(complete=1),
    )

    assert item.pmid_count == 0
    assert item.source_count == 0
    assert item.passage_count == 0
    assert item.approximate_bytes == 0
    assert item.expires_at is None


def test_list_review_indexes_response_wraps_inventory_items() -> None:
    response = ListReviewIndexesResponse(indexes=[])

    assert response.success is True
    assert response.indexes == []


def test_evidence_tier_derives_from_actual_coverage() -> None:
    assert coverage_to_evidence_tier("full_text", "pubtator_full_bioc") == (
        EvidenceTier.PASSAGE_FULL_TEXT
    )
    assert coverage_to_evidence_tier("abstract_only", "pubtator_abstract") == (
        EvidenceTier.PASSAGE_ABSTRACT
    )
    assert coverage_to_evidence_tier("title_only", "pubtator_abstract") == (
        EvidenceTier.METADATA_TITLE
    )
    assert coverage_to_evidence_tier("curated_url", "curated_pdf") == (
        EvidenceTier.CURATED_FULL_TEXT
    )
