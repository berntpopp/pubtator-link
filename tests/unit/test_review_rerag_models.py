import pytest
from pydantic import ValidationError

from pubtator_link.models.review_rerag import (
    ContextBudget,
    ContextPack,
    ContextPassage,
    EvidenceCertaintyRecord,
    EvidenceTier,
    GroundingConfidence,
    IndexReviewEvidenceRequest,
    ListReviewIndexesResponse,
    McpReviewAuditBundleResponse,
    PassageQuote,
    PreparationStatus,
    QueryDiagnosticsSummary,
    RecoveryBudgetAdvice,
    RecoveryHint,
    RecoverySuggestedFilters,
    ReviewAuditTrailItem,
    ResearchSessionCandidate,
    ResearchSessionManifest,
    ResolverAttemptSummary,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextRequest,
    ReviewAuditBundle,
    ReviewAuditTrailResponse,
    ReviewIndexInventoryItem,
    SourceDroppedSummary,
    ReviewIndexTotals,
    SourceCoverageHint,
    StageResearchSessionRequest,
    StageResearchSessionResponse,
    UpsertEvidenceCertaintyRequest,
    coverage_to_evidence_tier,
    normalize_section,
    passage_id_for_pmid,
)


def test_recovery_hint_serializes_bounded_filters_and_budget_advice() -> None:
    hint = RecoveryHint(
        reason="all_candidates_over_budget",
        message="Candidates matched but were excluded by response budget.",
        next_steps=["increase_budget", "filter_sections"],
        suggested_queries=["mefv colchicine"],
        suggested_filters=RecoverySuggestedFilters(
            sections=["abstract", "results"],
            pmids=["40234174"],
        ),
        budget_advice=RecoveryBudgetAdvice(
            increase_max_chars_to=18000,
            increase_max_response_chars_to=36000,
            lower_max_passages_per_query_to=4,
        ),
    )

    dumped = hint.model_dump(mode="json")

    assert dumped["reason"] == "all_candidates_over_budget"
    assert dumped["suggested_filters"]["sections"] == ["abstract", "results"]
    assert dumped["budget_advice"]["increase_max_chars_to"] == 18000


def test_context_passage_serializes_quote_and_grounding_confidence() -> None:
    passage = ContextPassage(
        citation_key="S1",
        passage_id="PMID:1:abstract:0",
        section="abstract",
        text="MEFV variants respond to colchicine in this cohort.",
        quote=PassageQuote(
            text="MEFV variants respond to colchicine",
            returned_start_offset=0,
            returned_end_offset=35,
            passage_start_char=10,
            passage_end_char=45,
        ),
        confidence_for_grounding=GroundingConfidence(
            level="high",
            score=0.84,
            factors={"lexical_match": 0.9, "section_weight": 0.8},
            match_mode="strict_and_relaxed",
            explanation="High lexical match in an abstract passage.",
        ),
    )

    dumped = passage.model_dump(mode="json")

    assert dumped["quote"]["passage_start_char"] == 10
    assert dumped["confidence_for_grounding"]["level"] == "high"
    assert dumped["stable_citation_key"].startswith("c_")


def test_context_pack_accepts_structured_dropped_summary_and_recovery() -> None:
    pack = ContextPack(
        question="MEFV colchicine",
        passages=[],
        citation_map={},
        dropped_summary=SourceDroppedSummary(
            total_dropped=3,
            visible_dropped=3,
            by_reason={"char_budget_exceeded": 3},
            suggested_filters=RecoverySuggestedFilters(sections=["abstract"]),
        ),
        recovery=RecoveryHint(
            reason="all_candidates_over_budget",
            message="Candidates matched but were excluded by response budget.",
            next_steps=["increase_budget"],
        ),
    )

    dumped = pack.model_dump(mode="json")

    assert dumped["dropped_summary"]["by_reason"] == {"char_budget_exceeded": 3}
    assert dumped["recovery"]["next_steps"] == ["increase_budget"]


def test_source_coverage_hint_includes_after_index_expectation() -> None:
    hint = SourceCoverageHint(
        pmid="40234174",
        expected_coverage="unknown",
        expected_coverage_after_index="abstract_only",
        expected_coverage_confidence="moderate",
        coverage_resolution_stage="preflight_resolver_chain",
    )

    dumped = hint.model_dump(mode="json")

    assert dumped["expected_coverage_after_index"] == "abstract_only"
    assert dumped["expected_coverage_confidence"] == "moderate"


def test_review_audit_trail_response_serializes_copy_ready_block() -> None:
    response = ReviewAuditTrailResponse(
        review_id="rev-1",
        items=[
            ReviewAuditTrailItem(
                pmid="40234174",
                passage_id="PMID:40234174:abstract:0",
                stable_citation_key="c_abc123",
                section="abstract",
                quote="MEFV variants respond to colchicine.",
                char_count=35,
            )
        ],
        audit_block="- c_abc123 PMID 40234174 PMID:40234174:abstract:0 abstract: MEFV variants respond to colchicine.",
    )

    dumped = response.model_dump(mode="json")

    assert dumped["items"][0]["stable_citation_key"] == "c_abc123"
    assert dumped["audit_block"].startswith("- c_abc123 PMID 40234174")


def test_index_request_rejects_screened_mode() -> None:
    with pytest.raises(ValidationError):
        IndexReviewEvidenceRequest(pmids=["40234174"], prepare_mode="screened")


def test_index_review_evidence_rejects_candidate_fast_prepare_mode() -> None:
    with pytest.raises(ValidationError):
        IndexReviewEvidenceRequest(pmids=["40234174"], prepare_mode="candidate_fast")


def test_stage_research_session_request_accepts_query_and_limits() -> None:
    request = StageResearchSessionRequest(
        query="familial mediterranean fever colchicine guideline",
        max_candidates=12,
        stage_full_text=True,
    )

    assert request.query == "familial mediterranean fever colchicine guideline"
    assert request.pmids == []
    assert request.max_candidates == 12
    assert request.stage_full_text is True


def test_stage_research_session_request_requires_query_or_pmids() -> None:
    with pytest.raises(ValidationError):
        StageResearchSessionRequest()


def test_research_session_candidate_records_decision_and_status() -> None:
    candidate = ResearchSessionCandidate(
        pmid="37747561",
        rank=1,
        status="queued",
        decision_reason="selected_by_rank",
    )

    assert candidate.pmid == "37747561"
    assert candidate.status == "queued"
    assert candidate.decision_reason == "selected_by_rank"


def test_stage_research_session_response_serializes_meta_alias_by_default() -> None:
    response = StageResearchSessionResponse(
        manifest=ResearchSessionManifest(session_id="session-1", review_id="review-1"),
        meta={"request_id": "req-1"},
    )

    dumped = response.model_dump(mode="json")

    assert dumped["_meta"] == {"request_id": "req-1"}
    assert "meta" not in dumped


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


def test_evidence_certainty_request_stores_grade_domains_without_computing() -> None:
    request = UpsertEvidenceCertaintyRequest(
        outcome="FMF attack recurrence",
        question="Does colchicine reduce attacks in FMF?",
        study_design="randomized trial",
        risk_of_bias_notes="Allocation concealment unclear in one study.",
        inconsistency_notes="Effects point in same direction.",
        indirectness_notes="Population matches review question.",
        imprecision_notes="Confidence interval crosses small benefit threshold.",
        publication_bias_notes="Small-study effects not assessed.",
        overall_certainty="moderate",
        certainty_rationale="Downgraded once for imprecision.",
        passage_ids=["PMID:123:abstract:0"],
        created_by="client:test",
    )

    assert request.overall_certainty == "moderate"
    assert request.passage_ids == ["PMID:123:abstract:0"]


def test_evidence_certainty_rejects_empty_outcome() -> None:
    with pytest.raises(ValidationError):
        UpsertEvidenceCertaintyRequest(outcome="", overall_certainty="not_rated")


def test_evidence_certainty_record_has_stable_identifier() -> None:
    record = EvidenceCertaintyRecord(
        certainty_id="00000000-0000-0000-0000-000000000001",
        review_id="review-1",
        outcome="Mortality",
        overall_certainty="low",
        created_at="2026-05-01T00:00:00Z",
        updated_at="2026-05-01T00:00:00Z",
    )

    assert record.review_id == "review-1"
    assert record.overall_certainty == "low"


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
