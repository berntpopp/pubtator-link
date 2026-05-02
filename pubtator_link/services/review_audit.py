from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from pubtator_link.models.review_rerag import (
    EvidenceCertaintyRecord,
    FailedSourceSummary,
    PreparationStatus,
    ResearchSessionManifest,
    ReviewAuditBundle,
    ReviewIndexTotals,
    ReviewRetrievalRun,
    ReviewSearchRun,
    ReviewSourceSummary,
    stable_citation_key_for_passage,
)
from pubtator_link.services.review_state import index_snapshot_date


class ReviewAuditRepository(Protocol):
    async def preparation_status(self, review_id: str) -> PreparationStatus | dict[str, int]:
        """Return preparation status for a review."""

    async def review_index_totals(self, review_id: str) -> ReviewIndexTotals:
        """Return index totals for a review."""

    async def list_review_sources(
        self,
        review_id: str,
        pmids: list[str] | None = None,
        *,
        include_passage_samples: bool = False,
        sample_per_pmid: int = 0,
    ) -> list[ReviewSourceSummary]:
        """Return indexed source summaries."""

    async def list_review_failed_sources(self, review_id: str) -> list[FailedSourceSummary]:
        """Return failed source summaries."""

    async def list_review_passage_ids(self, review_id: str) -> list[str]:
        """Return stable passage IDs for a review."""

    async def list_review_audit_events(self, review_id: str) -> list[Mapping[str, Any]]:
        """Return recorded audit events for a review."""

    async def list_evidence_certainty(self, review_id: str) -> list[EvidenceCertaintyRecord]:
        """Return user-supplied certainty records for a review."""

    async def list_research_sessions(self, review_id: str) -> list[ResearchSessionManifest]:
        """Return research session manifests for a review."""


class ReviewAuditService:
    def __init__(self, repository: ReviewAuditRepository) -> None:
        self.repository = repository

    async def export_bundle(self, review_id: str) -> ReviewAuditBundle:
        preparation_status = await self.repository.preparation_status(review_id)
        if not isinstance(preparation_status, PreparationStatus):
            preparation_status = PreparationStatus(**preparation_status)
        totals = await self.repository.review_index_totals(review_id)
        sources = await self.repository.list_review_sources(
            review_id,
            pmids=None,
            include_passage_samples=False,
            sample_per_pmid=0,
        )
        failed_sources = await self.repository.list_review_failed_sources(review_id)
        passage_ids = await self.repository.list_review_passage_ids(review_id)
        events = await self.repository.list_review_audit_events(review_id)
        evidence_certainty = await self.repository.list_evidence_certainty(review_id)
        research_sessions = await self.repository.list_research_sessions(review_id)
        search_runs, retrieval_runs = self._runs_from_events(events)
        coverage_distribution = Counter(source.coverage for source in sources)
        resolver_attempts = []
        for source in sources:
            resolver_attempts.extend(source.resolver_attempts)
        for failed_source in failed_sources:
            resolver_attempts.extend(failed_source.resolver_attempts)
        return ReviewAuditBundle(
            review_id=review_id,
            generated_at=datetime.now(UTC).isoformat(),
            preparation_status=preparation_status,
            totals=totals,
            sources=sources,
            failed_sources=failed_sources,
            coverage_distribution={str(key): value for key, value in coverage_distribution.items()},
            resolver_attempts=resolver_attempts,
            search_runs=search_runs,
            retrieval_runs=retrieval_runs,
            evidence_certainty=evidence_certainty,
            research_sessions=research_sessions,
            passage_ids=passage_ids,
            stable_citation_keys={
                passage_id: stable_citation_key_for_passage(passage_id)
                for passage_id in passage_ids
            },
            index_snapshot_date=index_snapshot_date(),
        )

    @staticmethod
    def _runs_from_events(
        events: list[Mapping[str, Any]],
    ) -> tuple[list[ReviewSearchRun], list[ReviewRetrievalRun]]:
        search_runs: list[ReviewSearchRun] = []
        retrieval_runs: list[ReviewRetrievalRun] = []
        for event in events:
            payload = dict(event.get("payload") or {})
            created_at = event.get("created_at")
            if event.get("event_type") == "search_run":
                search_runs.append(
                    ReviewSearchRun(
                        query=str(payload.get("query", "")),
                        filters=dict(payload.get("filters") or {}),
                        source=str(payload.get("source", "pubtator")),
                        returned_count=int(payload.get("returned_count") or 0),
                        created_at=str(created_at) if created_at is not None else None,
                    )
                )
            elif event.get("event_type") == "retrieval_run":
                retrieval_runs.append(
                    ReviewRetrievalRun(
                        queries=list(payload.get("queries") or []),
                        passage_ids=list(payload.get("passage_ids") or []),
                        created_at=str(created_at) if created_at is not None else None,
                    )
                )
        return search_runs, retrieval_runs
