from __future__ import annotations

import pytest

from pubtator_link.models.review_rerag import (
    EvidenceCertaintyRecord,
    PreparationStatus,
    ResearchSessionManifest,
    ResolverAttemptSummary,
    ReviewIndexTotals,
    ReviewSourceSummary,
)
from pubtator_link.services.review_audit import ReviewAuditService


class FakeAuditRepository:
    async def preparation_status(
        self, review_id: str, *, session_id: str | None = None
    ) -> PreparationStatus:
        return PreparationStatus(complete=1)

    async def review_index_totals(
        self, review_id: str, *, session_id: str | None = None
    ) -> ReviewIndexTotals:
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

    async def list_review_failed_sources(self, review_id: str, *, session_id: str | None = None):
        return []

    async def list_review_passage_ids(
        self, review_id: str, *, session_id: str | None = None
    ) -> list[str]:
        return ["PMID:1:title:0", "PMID:1:abstract:1"]

    async def list_review_audit_events(self, review_id: str, *, limit: int | None = None):
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

    async def list_evidence_certainty(self, review_id: str):
        return [
            EvidenceCertaintyRecord(
                certainty_id="00000000-0000-0000-0000-000000000001",
                review_id=review_id,
                outcome="Mortality",
                overall_certainty="low",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
            )
        ]

    async def list_research_sessions(self, review_id: str):
        return [
            ResearchSessionManifest(
                session_id="session-1",
                review_id=review_id,
                query="MEFV colchicine",
                candidate_count=2,
            )
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
    assert bundle.evidence_certainty[0].overall_certainty == "low"
    assert bundle.research_sessions[0].session_id == "session-1"
    assert bundle.passage_ids == ["PMID:1:title:0", "PMID:1:abstract:1"]
    assert bundle.stable_citation_keys["PMID:1:title:0"].startswith("c_")
    assert bundle.index_snapshot_date is not None


@pytest.mark.asyncio
async def test_review_audit_bundle_ignores_malformed_event_payloads() -> None:
    class MalformedPayloadRepository(FakeAuditRepository):
        async def list_review_audit_events(self, review_id: str, *, limit: int | None = None):
            return [
                {
                    "event_type": "search_run",
                    "payload": "not-json",
                    "created_at": "2026-05-01T10:00:00+00:00",
                },
                {
                    "event_type": "retrieval_run",
                    "payload": ["bad"],
                    "created_at": "2026-05-01T10:01:00+00:00",
                },
                {
                    "event_type": "search_run",
                    "payload": (
                        '{"query":"MEFV VUS","filters":{"year_min":2020},"returned_count":5}'
                    ),
                    "created_at": "2026-05-01T10:02:00+00:00",
                },
            ]

    bundle = await ReviewAuditService(MalformedPayloadRepository()).export_bundle("review-1")

    assert [run.query for run in bundle.search_runs] == ["", "MEFV VUS"]
    assert bundle.search_runs[1].filters == {"year_min": 2020}
    assert bundle.search_runs[1].returned_count == 5
    assert bundle.retrieval_runs[0].queries == []


@pytest.mark.asyncio
async def test_review_audit_resource_summary_uses_bounded_events() -> None:
    class BoundedEventRepository(FakeAuditRepository):
        seen_limit: int | None = None

        async def list_review_audit_events(self, review_id: str, *, limit: int | None = None):
            self.seen_limit = limit
            return []

    repository = BoundedEventRepository()

    summary = await ReviewAuditService(repository).get_resource_summary("review-1")

    assert summary["success"] is True
    assert summary["review_id"] == "review-1"
    assert repository.seen_limit == 20


@pytest.mark.asyncio
async def test_review_audit_bundle_records_session_id() -> None:
    bundle = await ReviewAuditService(FakeAuditRepository()).export_bundle(
        "review-1",
        session_id="session-1",
    )

    assert bundle.session_id == "session-1"
