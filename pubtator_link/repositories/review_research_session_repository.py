"""Research-session persistence methods for the review repository."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pubtator_link.models.research_session_list import ResearchSessionSummary
from pubtator_link.models.review_rerag import (
    ResearchSessionCandidate,
    ResearchSessionManifest,
)
from pubtator_link.repositories import review_research_sessions
from pubtator_link.repositories.review_rerag_mappers import (
    _research_session_candidate_from_row,
)


class ReviewResearchSessionRepositoryMixin:
    """Persist detailed sessions and serve compact candidate-free list pages."""

    _acquire: Callable[[], Any]

    async def upsert_research_session(
        self,
        *,
        review_id: str,
        session_id: str,
        query: str | None,
        status: str,
        request: dict[str, Any],
    ) -> None:
        async with self._acquire() as connection:
            await connection.execute(
                """
                insert into reviews (review_id)
                values ($1)
                on conflict (review_id) do update
                set updated_at = now()
                """,
                review_id,
            )
            await connection.execute(
                """
                insert into review_research_sessions
                    (review_id, session_id, query, status, request, updated_at)
                values ($1, $2, $3, $4, $5::jsonb, now())
                on conflict (review_id, session_id) do update set
                    query = excluded.query,
                    status = excluded.status,
                    request = excluded.request,
                    updated_at = now()
                """,
                review_id,
                session_id,
                query,
                status,
                json.dumps(request),
            )

    async def upsert_research_session_candidate(
        self,
        *,
        review_id: str,
        session_id: str,
        candidate: ResearchSessionCandidate,
    ) -> None:
        coverage_hint = (
            json.dumps(candidate.coverage_hint.model_dump(mode="json"))
            if candidate.coverage_hint
            else None
        )
        async with self._acquire() as connection:
            await connection.execute(
                """
                insert into review_research_session_candidates
                    (review_id, session_id, pmid, rank, title, status, decision_reason,
                     coverage_hint, source_id, error, updated_at)
                values ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10, now())
                on conflict (review_id, session_id, pmid) do update set
                    rank = excluded.rank,
                    title = excluded.title,
                    status = excluded.status,
                    decision_reason = excluded.decision_reason,
                    coverage_hint = excluded.coverage_hint,
                    source_id = excluded.source_id,
                    error = excluded.error,
                    updated_at = now()
                """,
                review_id,
                session_id,
                candidate.pmid,
                candidate.rank,
                candidate.title,
                candidate.status,
                candidate.decision_reason,
                coverage_hint,
                candidate.source_id,
                candidate.error,
            )

    async def get_research_session(
        self, review_id: str, session_id: str
    ) -> ResearchSessionManifest | None:
        async with self._acquire() as connection:
            session = await connection.fetchrow(
                """
                select review_id, session_id, query, status,
                       created_at::text as created_at, updated_at::text as updated_at
                from review_research_sessions
                where review_id = $1 and session_id = $2
                """,
                review_id,
                session_id,
            )
            if session is None:
                return None
            rows = await connection.fetch(
                """
                select pmid, rank, title, status, decision_reason, coverage_hint,
                       source_id, error
                from review_research_session_candidates
                where review_id = $1 and session_id = $2
                order by rank nulls last, pmid
                """,
                review_id,
                session_id,
            )
        candidates = [_research_session_candidate_from_row(row) for row in rows]
        return ResearchSessionManifest(
            review_id=session["review_id"],
            session_id=session["session_id"],
            query=session["query"],
            status=session["status"],
            candidates=candidates,
            candidate_count=len(candidates),
            queued_count=sum(1 for item in candidates if item.status == "queued"),
            skipped_count=sum(1 for item in candidates if item.status == "skipped"),
            coverage_summary=_coverage_summary(candidates),
            created_at=session["created_at"],
            updated_at=session["updated_at"],
        )

    async def list_research_sessions(self, review_id: str) -> list[ResearchSessionManifest]:
        return await review_research_sessions.list_research_sessions_for_review(
            self._acquire, review_id
        )

    async def list_research_sessions_global(self, limit: int = 20) -> list[ResearchSessionManifest]:
        return await review_research_sessions.list_research_sessions_global(
            self._acquire, limit=limit
        )

    async def list_research_session_summaries(
        self,
        *,
        review_id: str | None,
        limit: int,
        before_updated_at: datetime | None,
        before_session_id: str | None,
        before_review_id: str | None,
    ) -> list[ResearchSessionSummary]:
        return await review_research_sessions.list_research_session_summaries(
            self._acquire,
            review_id=review_id,
            limit=limit,
            before_updated_at=before_updated_at,
            before_session_id=before_session_id,
            before_review_id=before_review_id,
        )

    async def find_research_sessions_by_session_id(
        self, session_id: str
    ) -> list[ResearchSessionManifest]:
        return await review_research_sessions.find_research_sessions_by_session_id(
            self._acquire, session_id
        )


def _coverage_summary(candidates: list[ResearchSessionCandidate]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for candidate in candidates:
        coverage = (
            candidate.coverage_hint.expected_coverage
            if candidate.coverage_hint is not None
            else "unknown"
        )
        summary[coverage] = summary.get(coverage, 0) + 1
    return summary
