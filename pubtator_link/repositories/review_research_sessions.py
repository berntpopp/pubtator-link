from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pubtator_link.models.research_session_list import ResearchSessionSummary
from pubtator_link.models.review_rerag import (
    ResearchSessionCandidate,
    ResearchSessionManifest,
)
from pubtator_link.repositories.review_rerag_mappers import (
    _research_session_candidate_from_row,
)


def _manifest_from_session_row(
    session: Mapping[str, Any],
    candidates: list[ResearchSessionCandidate],
) -> ResearchSessionManifest:
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


def _manifests_from_rows(
    sessions: list[Mapping[str, Any]],
    candidate_rows: list[Mapping[str, Any]],
    *,
    default_review_id: str | None = None,
) -> list[ResearchSessionManifest]:
    candidates_by_session: dict[tuple[str, str], list[ResearchSessionCandidate]] = {}
    for row in candidate_rows:
        review_id = str(row.get("review_id") or default_review_id or "")
        key = (review_id, row["session_id"])
        candidates_by_session.setdefault(key, []).append(_research_session_candidate_from_row(row))
    return [
        _manifest_from_session_row(
            session,
            candidates_by_session.get((session["review_id"], session["session_id"]), []),
        )
        for session in sessions
    ]


async def list_research_sessions_global(
    acquire: Callable[[], Any], *, limit: int = 20
) -> list[ResearchSessionManifest]:
    async with (
        acquire() as connection,
        connection.transaction(isolation="repeatable_read", readonly=True),
    ):
        sessions = await connection.fetch(
            """
            select review_id, session_id, query, status,
                   created_at::text as created_at, updated_at::text as updated_at
            from review_research_sessions
            order by updated_at desc, created_at desc, review_id, session_id
            limit $1
            """,
            limit,
        )
        if not sessions:
            return []
        candidate_rows = await connection.fetch(
            """
            select review_id, session_id, pmid, rank, title, status, decision_reason,
                   coverage_hint, source_id, error
            from review_research_session_candidates
            where (review_id, session_id) in (
                select review_id, session_id
                from review_research_sessions
                order by updated_at desc, created_at desc, review_id, session_id
                limit $1
            )
            order by review_id, session_id, rank nulls last, pmid
            """,
            limit,
        )
    return _manifests_from_rows(sessions, candidate_rows)


async def list_research_sessions_for_review(
    acquire: Callable[[], Any], review_id: str
) -> list[ResearchSessionManifest]:
    async with (
        acquire() as connection,
        connection.transaction(isolation="repeatable_read", readonly=True),
    ):
        sessions = await connection.fetch(
            """
            select review_id, session_id, query, status,
                   created_at::text as created_at, updated_at::text as updated_at
            from review_research_sessions
            where review_id = $1
            order by updated_at desc, session_id
            """,
            review_id,
        )
        if not sessions:
            return []
        candidate_rows = await connection.fetch(
            """
            select review_id, session_id, pmid, rank, title, status, decision_reason,
                   coverage_hint, source_id, error
            from review_research_session_candidates
            where review_id = $1
            order by session_id, rank nulls last, pmid
            """,
            review_id,
        )
    return _manifests_from_rows(sessions, candidate_rows, default_review_id=review_id)


async def list_research_session_summaries(
    acquire: Callable[[], Any],
    *,
    review_id: str | None,
    limit: int,
    before_updated_at: str | None,
    before_session_id: str | None,
    before_review_id: str | None,
) -> list[ResearchSessionSummary]:
    """Fetch a compact page without reading session candidate rows."""
    base_sql = """
        select sessions.review_id, sessions.session_id, sessions.query, sessions.status,
               sessions.updated_at::text as updated_at,
               count(candidates.pmid)::integer as candidate_count
        from review_research_sessions as sessions
        left join review_research_session_candidates as candidates
          on candidates.review_id = sessions.review_id
         and candidates.session_id = sessions.session_id
    """
    if review_id is not None:
        scope_sql = "where sessions.review_id = $1"
        if before_session_id is None:
            cursor_sql = ""
            args: tuple[Any, ...] = (review_id, limit)
            limit_param = "$2"
        elif before_updated_at is None:
            cursor_sql = "and sessions.updated_at is null and sessions.session_id < $2"
            args = (review_id, before_session_id, limit)
            limit_param = "$3"
        else:
            cursor_sql = """
                and (
                    sessions.updated_at < $2::timestamptz
                    or (sessions.updated_at = $2::timestamptz and sessions.session_id < $3)
                    or sessions.updated_at is null
                )
            """
            args = (review_id, before_updated_at, before_session_id, limit)
            limit_param = "$4"
    elif before_session_id is None:
        scope_sql = ""
        cursor_sql = ""
        args = (limit,)
        limit_param = "$1"
    elif before_updated_at is None:
        scope_sql = """
            where sessions.updated_at is null
              and (
                  sessions.session_id < $1
                  or (sessions.session_id = $1 and sessions.review_id < $2)
              )
        """
        cursor_sql = ""
        args = (before_session_id, before_review_id, limit)
        limit_param = "$3"
    else:
        scope_sql = """
            where (
                sessions.updated_at < $1::timestamptz
                or (
                    sessions.updated_at = $1::timestamptz
                    and (
                        sessions.session_id < $2
                        or (sessions.session_id = $2 and sessions.review_id < $3)
                    )
                )
                or sessions.updated_at is null
            )
        """
        cursor_sql = ""
        args = (before_updated_at, before_session_id, before_review_id, limit)
        limit_param = "$4"
    sql = f"""
        {base_sql}
        {scope_sql}
        {cursor_sql}
        group by sessions.review_id, sessions.session_id, sessions.query, sessions.status,
                 sessions.updated_at
        order by sessions.updated_at desc nulls last, sessions.session_id desc, sessions.review_id desc
        limit {limit_param}
    """
    async with (
        acquire() as connection,
        connection.transaction(isolation="repeatable_read", readonly=True),
    ):
        rows = await connection.fetch(sql, *args)
    return [ResearchSessionSummary.model_validate(row) for row in rows]


async def find_research_sessions_by_session_id(
    acquire: Callable[[], Any], session_id: str
) -> list[ResearchSessionManifest]:
    async with (
        acquire() as connection,
        connection.transaction(isolation="repeatable_read", readonly=True),
    ):
        sessions = await connection.fetch(
            """
            select review_id, session_id, query, status,
                   created_at::text as created_at, updated_at::text as updated_at
            from review_research_sessions
            where session_id = $1
            order by updated_at desc, created_at desc, review_id
            """,
            session_id,
        )
        if not sessions:
            return []
        candidate_rows = await connection.fetch(
            """
            select review_id, session_id, pmid, rank, title, status, decision_reason,
                   coverage_hint, source_id, error
            from review_research_session_candidates
            where session_id = $1
            order by review_id, session_id, rank nulls last, pmid
            """,
            session_id,
        )
    return _manifests_from_rows(sessions, candidate_rows)
