from __future__ import annotations

import json

from pubtator_link.repositories.review_rerag_mappers import (
    _evidence_certainty_from_row,
    _infer_source_coverage,
    _parse_execute_count,
    _passage_from_row,
    _preparation_status_from_row,
    _recall_tsquery,
    _research_session_candidate_from_row,
    _review_inventory_item_from_row,
    _source_summary_from_row,
)


def test_preparation_status_from_missing_row_defaults_to_zero() -> None:
    status = _preparation_status_from_row(None)

    assert status.total == 0
    assert status.failed == 0


def test_passage_from_row_decodes_json_metadata() -> None:
    row = {
        "passage_id": "p1",
        "review_id": "r1",
        "source_id": "s1",
        "source_kind": "pubtator_abstract",
        "pmid": "123",
        "pmcid": None,
        "doi": None,
        "url": None,
        "section": "abstract",
        "heading_path": "Abstract",
        "page": None,
        "text": "MEFV colchicine evidence",
        "entity_ids": ["@GENE_MEFV"],
        "relation_types": [],
        "screening_status": "included",
        "source_metadata": json.dumps({"journal": "Example"}),
        "lexical_rank": 2.5,
    }

    passage = _passage_from_row(row)

    assert passage.passage_id == "p1"
    assert passage.source_metadata == {"journal": "Example"}
    assert passage.lexical_rank == 2.5


def test_infer_source_coverage_prefers_full_text_sections() -> None:
    assert (
        _infer_source_coverage(
            source_kind="pubtator_full_bioc",
            sections=["abstract", "results"],
            attempt_statuses=[],
        )
        == "full_text"
    )
    assert (
        _infer_source_coverage(
            source_kind="pubtator_abstract",
            sections=["abstract"],
            attempt_statuses=[],
        )
        == "abstract_only"
    )


def test_source_summary_maps_coverage_and_resolver_attempt_metadata() -> None:
    summary = _source_summary_from_row(
        {
            "source_id": "PMID:40234174",
            "pmid": "40234174",
            "source_kind": "pubtator_full_bioc",
            "job_status": "partial",
            "error": None,
            "attempt_statuses": ["pubtator_full_bioc:failed", "pubtator_abstract:success"],
            "sections": ["title", "abstract"],
            "passage_count": 2,
            "char_count": 500,
            "coverage_reason": "abstract_fallback_used",
            "pmcid": "PMC123",
            "doi": "10.1000/example",
            "license_or_access_hint": "oa",
            "pmc_fallback_available": True,
            "resolver_attempts": [
                {
                    "source_kind": "pubtator_full_bioc",
                    "status": "failed",
                    "attempt_count": 3,
                    "last_status_code": 503,
                    "retry_after_ms": 1000,
                    "backoff_ms": 750,
                    "terminal_reason": "retry_exhausted",
                    "pmid": "40234174",
                    "pmcid": "PMC123",
                    "doi": "10.1000/example",
                }
            ],
        }
    )

    assert summary.coverage_reason == "abstract_fallback_used"
    assert summary.pmcid == "PMC123"
    assert summary.doi == "10.1000/example"
    assert summary.license_or_access_hint == "oa"
    assert summary.pmc_fallback_available is True
    assert len(summary.resolver_attempts) == 1
    assert summary.resolver_attempts[0].attempt_count == 3
    assert summary.resolver_attempts[0].last_status_code == 503


def test_parse_execute_count_and_recall_query_are_stable() -> None:
    assert _parse_execute_count("INSERT 0 7") == 7
    assert _parse_execute_count("UPDATE") == 0
    assert _recall_tsquery("MEFV MEFV colchicine response in FMF") == (
        "mefv | colchicine | response | fmf"
    )


def test_review_inventory_mapper_builds_item_from_aggregate_row() -> None:
    row = {
        "review_id": "review-1",
        "created_at": "2026-05-01T00:00:00Z",
        "updated_at": "2026-05-01T01:00:00Z",
        "queued": 0,
        "running": 0,
        "complete": 1,
        "partial": 0,
        "failed": 0,
        "pmid_count": 1,
        "source_count": 1,
        "passage_count": 2,
        "failed_source_count": 0,
        "approximate_bytes": 1234,
    }

    item = _review_inventory_item_from_row(row, ttl_seconds=3600)

    assert item.review_id == "review-1"
    assert item.preparation_status.complete == 1
    assert item.approximate_bytes == 1234
    assert item.expires_at is not None


def test_evidence_certainty_mapper_preserves_grade_notes() -> None:
    row = {
        "certainty_id": "00000000-0000-0000-0000-000000000001",
        "review_id": "review-1",
        "outcome": "Mortality",
        "question": "Question",
        "study_design": "observational",
        "risk_of_bias_notes": "Serious",
        "inconsistency_notes": None,
        "indirectness_notes": None,
        "imprecision_notes": None,
        "publication_bias_notes": None,
        "overall_certainty": "low",
        "certainty_rationale": "Downgraded twice.",
        "passage_ids": ["PMID:1:abstract:0"],
        "unresolved_passage_ids": [],
        "created_by": "client:test",
        "created_at": "2026-05-01T00:00:00Z",
        "updated_at": "2026-05-01T00:00:00Z",
    }

    record = _evidence_certainty_from_row(row)

    assert record.overall_certainty == "low"
    assert record.risk_of_bias_notes == "Serious"
    assert record.passage_ids == ["PMID:1:abstract:0"]


def test_research_session_candidate_mapper_parses_coverage_hint() -> None:
    row = {
        "pmid": "37747561",
        "rank": 1,
        "title": "Colchicine in familial Mediterranean fever",
        "status": "queued",
        "decision_reason": "selected_by_rank",
        "coverage_hint": {
            "pmid": "37747561",
            "expected_coverage": "full_text",
            "coverage_reason": "full_text_available",
            "pmc_fallback_available": True,
            "resolver_attempts": [],
        },
        "source_id": "PMID:37747561",
        "error": None,
    }

    candidate = _research_session_candidate_from_row(row)

    assert candidate.pmid == "37747561"
    assert candidate.coverage_hint is not None
    assert candidate.coverage_hint.expected_coverage == "full_text"
