from __future__ import annotations

import pytest

from pubtator_link.models.review_rerag import (
    PreparationStatus,
    ResolverAttemptSummary,
    ReviewIndexTotals,
    ReviewSourceSummary,
)
from pubtator_link.services.review_audit import ReviewAuditService


class FakeAuditRepository:
    async def preparation_status(self, review_id: str) -> PreparationStatus:
        return PreparationStatus(complete=1)

    async def review_index_totals(self, review_id: str) -> ReviewIndexTotals:
        return ReviewIndexTotals(pmid_count=1, source_count=1, passage_count=2, char_count=42)

    async def list_review_sources(self, review_id: str, pmids=None, **kwargs):
        return [
            ReviewSourceSummary(
                source_id="PMID:1",
                pmid="1",
                source_kind="pubtator_full_bioc",
                job_status="complete",
                coverage="full_text",
                coverage_reason="full_text_available",
                resolver_attempts=[
                    ResolverAttemptSummary(
                        source_kind="pubtator_full_bioc",
                        status="success",
                        pmid="1",
                    )
                ],
            )
        ]

    async def list_review_failed_sources(self, review_id: str):
        return []

    async def list_review_passage_ids(self, review_id: str) -> list[str]:
        return ["PMID:1:title:0", "PMID:1:abstract:1"]

    async def list_review_audit_events(self, review_id: str):
        return [
            {
                "event_type": "search_run",
                "payload": {
                    "query": "MEFV colchicine",
                    "filters": {"year_min": 2020},
                    "returned_count": 3,
                },
                "created_at": "2026-05-01T10:00:00+00:00",
            },
            {
                "event_type": "retrieval_run",
                "payload": {
                    "queries": ["MEFV diagnosis", "colchicine response"],
                    "passage_ids": ["PMID:1:title:0", "PMID:1:abstract:1"],
                },
                "created_at": "2026-05-01T10:01:00+00:00",
            },
        ]


@pytest.mark.asyncio
async def test_review_audit_bundle_exports_sources_attempts_events_and_citation_keys() -> None:
    bundle = await ReviewAuditService(FakeAuditRepository()).export_bundle("review-1")

    assert bundle.review_id == "review-1"
    assert bundle.generated_at is not None
    assert bundle.preparation_status.complete == 1
    assert bundle.totals.passage_count == 2
    assert bundle.sources[0].coverage_reason == "full_text_available"
    assert bundle.coverage_distribution["full_text"] == 1
    assert bundle.resolver_attempts[0].source_kind == "pubtator_full_bioc"
    assert bundle.search_runs[0].query == "MEFV colchicine"
    assert bundle.retrieval_runs[0].queries == ["MEFV diagnosis", "colchicine response"]
    assert bundle.passage_ids == ["PMID:1:title:0", "PMID:1:abstract:1"]
    assert bundle.stable_citation_keys["PMID:1:title:0"].startswith("c_")
